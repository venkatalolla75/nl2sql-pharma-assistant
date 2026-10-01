"""
Regression tests for four bugs found testing the live deployment as an Exec:

1. A multi-turn follow-up ("What's the WAC revenue for our top product?" -> "Break that
   down by month") failed with "it may have asked for data outside your access level"
   for an Exec, who has full access. Root cause: the first turn's query itself timed out
   (unfiltered aggregate over 2M rows on RDS's small buffer cache), and the generic error
   message always blamed "access level" regardless of actual cause; the wrong message
   then got replayed into history, breaking the follow-up too.
2. Answers claimed results were "scoped to your territory" even for an Exec, who has no
   such restriction.
3. Answers didn't state the time period the results cover, and had no sensible default
   when the question didn't name one.
4. Revenue/sales figures must follow docs/data_source_guide.md and
   docs/metric_definitions.md: paid demand only (data_source='distributor' AND
   brand_flag=1), hub_dispense and market_data excluded by default.
5. "Who are our top 10 accounts by volume?" (no period named) timed out — the
   prompt-level default-period instruction is advisory, and the model has
   repeatedly just not followed it. Fixed with a backend backstop
   (sql_guard.ensure_default_period) that injects the default filter into the
   validated SQL when the model's own query never filtered by an offset column.

Requires AWS credentials with Bedrock access (skipped otherwise — see conftest.py).
"""

import re

import psycopg
import pytest

from app.db import scoped_cursor
from app.main import _access_note
from app.periods import period_note
from tests.conftest import LIVE_URL, requires_bedrock

pytestmark = requires_bedrock


# ---------------------------------------------------------------------------
# Issue 1 — multi-turn WAC follow-up must not crash, for every role
# ---------------------------------------------------------------------------

def test_wac_top_product_multiturn_no_timeout_exec(login, users, report):
    """The exact repro from the live bug report."""
    c = login(users["exec"])
    q1 = "What's the WAC revenue for our top product?"
    r1 = c.post("/chat", json={"message": q1, "show_sql": True})
    b1 = r1.json()
    ok1 = r1.status_code == 200 and b1.get("row_count", 0) > 0 and "error" not in b1

    q2 = "Break that down by month"
    r2 = c.post("/chat", json={"message": q2, "show_sql": True})
    b2 = r2.json()
    ok2 = r2.status_code == 200 and b2.get("row_count", 0) > 0 and "error" not in b2

    ok = ok1 and ok2
    report.record(
        "NL-to-SQL Accuracy", "Exec: WAC top-product multi-turn (bug repro)", ok,
        question=f"[turn 1] {q1}  ->  [turn 2] {q2}",
        sql=b2.get("sql"),
        expected="both turns succeed (200, rows returned, no error)",
        actual=f"turn1: status={r1.status_code} row_count={b1.get('row_count')} "
               f"error={b1.get('error')!r} | "
               f"turn2: status={r2.status_code} row_count={b2.get('row_count')} "
               f"error={b2.get('error')!r}",
    )
    assert ok, f"turn1={b1!r} turn2={b2!r}"


def test_director_multiturn_followup(login, users, report):
    c = login(users["director_northeast"])
    q1 = "What are our top accounts by pack units this quarter?"
    r1 = c.post("/chat", json={"message": q1, "show_sql": True})
    b1 = r1.json()
    assert r1.status_code == 200, r1.text

    q2 = "Now just show me the top 3"
    r2 = c.post("/chat", json={"message": q2, "show_sql": True})
    b2 = r2.json()
    ok = r2.status_code == 200 and 0 < b2.get("row_count", 0) <= 3
    report.record(
        "NL-to-SQL Accuracy", "Director: multi-turn follow-up (top accounts -> top 3)", ok,
        question=f"[turn 1] {q1}  ->  [turn 2] {q2}", sql=b2.get("sql"),
        expected="turn 2 returns 1-3 rows, refining turn 1's query",
        actual=f"turn 1 rows={b1.get('row_count')}, turn 2 rows={b2.get('row_count')}",
    )
    assert ok, f"turn2={b2!r}"


def test_ram_multiturn_followup(login, users, report):
    c = login(users["ram_ny_metro"])
    q1 = "What's my total sales volume in pack units this month?"
    r1 = c.post("/chat", json={"message": q1, "show_sql": True})
    b1 = r1.json()
    assert r1.status_code == 200, r1.text

    q2 = "What about last month instead?"
    r2 = c.post("/chat", json={"message": q2, "show_sql": True})
    b2 = r2.json()
    ok = r2.status_code == 200 and "error" not in b2
    report.record(
        "NL-to-SQL Accuracy", "RAM: multi-turn follow-up (this month -> last month)", ok,
        question=f"[turn 1] {q1}  ->  [turn 2] {q2}", sql=b2.get("sql"),
        expected="turn 2 succeeds and refines the period to last month",
        actual=f"turn1 answer={b1.get('answer')!r} | turn2 answer={b2.get('answer')!r}",
    )
    assert ok, f"turn2={b2!r}"


def test_error_message_only_blames_access_level_for_real_permission_denial(
    login, users, monkeypatch, report
):
    """Force a non-permission DB failure (e.g. what a statement timeout looks like to
    the app) and confirm the friendly message does NOT claim it's an access problem."""
    if LIVE_URL:
        pytest.skip("monkeypatches app.main.scoped_cursor in this process - only "
                    "affects the in-process app, not a remote deployed server")
    import app.main as main_module

    from contextlib import contextmanager

    @contextmanager
    def _raise_query_canceled(*_a, **_k):
        raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")
        yield  # pragma: no cover

    monkeypatch.setattr(main_module, "scoped_cursor", _raise_query_canceled)

    c = login(users["exec"])
    resp = c.post("/chat", json={"message": "Show me every sale ever made.",
                                  "show_sql": True})
    body = resp.json()
    answer_lower = body.get("answer", "").lower()
    ok = (
        resp.status_code == 200
        and "access level" not in answer_lower
        and ("rephras" in answer_lower or "narrow" in answer_lower
             or "simpl" in answer_lower or "complex" in answer_lower)
    )
    report.record(
        "Security (live chat)", "Non-permission DB error gets an accurate message", ok,
        question="(monkeypatched scoped_cursor to raise QueryCanceled)",
        expected="answer does not blame 'access level'; suggests rephrasing/narrowing",
        actual=body.get("answer"),
    )
    assert ok, body


def test_error_message_blames_access_level_only_when_db_actually_denies(
    login, users, monkeypatch, report
):
    """The inverse: a genuine InsufficientPrivilege SHOULD produce the access-level
    message (this is the one case where that wording is accurate)."""
    if LIVE_URL:
        pytest.skip("monkeypatches app.main.scoped_cursor in this process - only "
                    "affects the in-process app, not a remote deployed server")
    import app.main as main_module

    from contextlib import contextmanager

    @contextmanager
    def _raise_insufficient_privilege(*_a, **_k):
        raise psycopg.errors.InsufficientPrivilege("permission denied for table sales")
        yield  # pragma: no cover

    monkeypatch.setattr(main_module, "scoped_cursor", _raise_insufficient_privilege)

    c = login(users["exec"])
    resp = c.post("/chat", json={"message": "Show me total sales.", "show_sql": True})
    body = resp.json()
    ok = resp.status_code == 200 and "access level" in body.get("answer", "").lower()
    report.record(
        "Security (live chat)", "Genuine permission denial gets the access-level message", ok,
        question="(monkeypatched scoped_cursor to raise InsufficientPrivilege)",
        expected="answer states it's an access-level problem",
        actual=body.get("answer"),
    )
    assert ok, body


def test_h4_invalid_column_error_gets_a_distinct_message_not_too_complex(
    login, users, monkeypatch, report
):
    """H4 (QA report): a hallucinated column (e.g. a non-existent period_yr) must not get
    the same "too complex or slow" message as a genuine statement timeout — that's
    actively misleading, since the query failed instantly on a bad reference, not because
    it was too big."""
    if LIVE_URL:
        pytest.skip("monkeypatches app.main.scoped_cursor in this process - only "
                    "affects the in-process app, not a remote deployed server")
    import app.main as main_module

    from contextlib import contextmanager

    @contextmanager
    def _raise_undefined_column(*_a, **_k):
        raise psycopg.errors.UndefinedColumn('column "period_yr" does not exist')
        yield  # pragma: no cover

    monkeypatch.setattr(main_module, "scoped_cursor", _raise_undefined_column)

    c = login(users["exec"])
    resp = c.post("/chat", json={"message": "Compare Q1 2026 vs Q1 2025.",
                                  "show_sql": True})
    body = resp.json()
    answer_lower = body.get("answer", "").lower()
    ok = (
        resp.status_code == 200
        and "too complex or slow" not in answer_lower
        and "access level" not in answer_lower
        and ("doesn't exist" in answer_lower or "does not exist" in answer_lower
             or "field" in answer_lower or "column" in answer_lower)
    )
    report.record(
        "Security (live chat)", "Invalid-column DB error gets a distinct message", ok,
        question="(monkeypatched scoped_cursor to raise UndefinedColumn)",
        expected="answer names a missing/invalid field, not 'too complex or slow'",
        actual=body.get("answer"),
    )
    assert ok, body


# ---------------------------------------------------------------------------
# Issue 2 — scope wording must match the actual role, never hallucinated
# ---------------------------------------------------------------------------

def test_access_note_exec_never_claims_a_scope_restriction():
    assert _access_note("exec", "Compare all territories by total pack units") is None
    assert _access_note("exec", "What's our revenue this month?") is None


def test_access_note_director_says_region_not_territory():
    note = _access_note("director", "Compare all territories by total pack units")
    assert note is not None
    assert "region" in note
    assert "territory only" not in note  # shouldn't call it a territory restriction


def test_access_note_ram_says_territory():
    note = _access_note("ram", "Compare all territories by total pack units")
    assert note is not None
    assert "territory" in note


def test_exec_answer_never_claims_scoped_to_territory(login, users, report):
    c = login(users["exec"])
    resp = c.post("/chat", json={
        "message": "Compare all territories by total pack units this quarter.",
        "show_sql": True,
    })
    body = resp.json()
    answer_lower = body.get("answer", "").lower()
    ok = (
        resp.status_code == 200
        and "scoped to your territory" not in answer_lower
        and "limited to your territory" not in answer_lower
        and "limited to your region" not in answer_lower
    )
    report.record(
        "Security (live chat)", "Exec answer never claims a false scope restriction", ok,
        question="Compare all territories by total pack units this quarter.",
        sql=body.get("sql"),
        expected="no claim that results are scoped/limited to a territory or region",
        actual=body.get("answer"),
    )
    assert ok, body


# ---------------------------------------------------------------------------
# Issue 3 — answers state the time period, with a sensible default when unspecified
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sql,expect_substring", [
    ("SELECT SUM(wac) FROM sales WHERE data_source='distributor' AND brand_flag=1 "
     "AND mo_offset = 0", "current month"),
    ("SELECT SUM(wac) FROM sales WHERE data_source='distributor' AND brand_flag=1 "
     "AND mo_offset IN (0,1,2)", "R3M"),
    ("SELECT SUM(wac) FROM sales WHERE data_source='distributor' AND brand_flag=1 "
     "AND mo_offset IN (3,4,5)", "R6M"),
    ("SELECT SUM(wac) FROM sales WHERE data_source='distributor' AND brand_flag=1 "
     "AND mo_offset IN (1,2,3)", "last quarter"),
])
def test_period_note_matches_documented_offset_patterns(sql, expect_substring):
    note = period_note(sql)
    assert note is not None
    assert expect_substring.lower() in note.lower()


def test_period_note_none_when_no_offset_filter_present():
    assert period_note("SELECT * FROM products WHERE brand_flag = 1") is None


def test_top_product_question_defaults_to_r3m_and_states_period(login, users, report):
    c = login(users["exec"])
    resp = c.post("/chat", json={
        "message": "What's the WAC revenue for our top product?", "show_sql": True,
    })
    body = resp.json()
    sql_lower = (body.get("sql") or "").lower()
    answer = body.get("answer", "")
    ok = (
        resp.status_code == 200
        and re.search(r"mo_offset\s+in\s*\(\s*0\s*,\s*1\s*,\s*2\s*\)", sql_lower)
        and re.search(r"\b(19|20)\d{2}\b", answer)  # states an actual year
    )
    report.record(
        "NL-to-SQL Accuracy", "No period given -> defaults to R3M, states it in the answer",
        ok, question="What's the WAC revenue for our top product?", sql=body.get("sql"),
        expected="SQL defaults to mo_offset IN (0,1,2); answer names a month",
        actual=answer,
    )
    assert ok, body


# ---------------------------------------------------------------------------
# Issue 4 — revenue/sales figures follow docs/ definitions (paid demand only)
# ---------------------------------------------------------------------------

def test_wac_revenue_question_excludes_hub_dispense_and_market_data(login, users, report):
    with scoped_cursor("exec", None, None) as cur:
        cur.execute(
            "SELECT SUM(wac) FROM sales "
            "WHERE data_source = 'distributor' AND brand_flag = 1 AND mo_offset = 0"
        )
        expected = float(cur.fetchone()[0] or 0)

    c = login(users["exec"])
    resp = c.post("/chat", json={
        "message": "What's our WAC revenue this month?", "show_sql": True,
    })
    body = resp.json()
    sql_lower = (body.get("sql") or "").lower()
    rows = body.get("rows") or []
    actual = None
    for row in rows:
        for cell in row:
            if isinstance(cell, (int, float)):
                actual = float(cell)
    close = actual is not None and abs(actual - expected) <= 0.08 * max(expected, 1)
    ok = (
        resp.status_code == 200
        and "distributor" in sql_lower
        and "hub_dispense" not in sql_lower
        and "market_data" not in sql_lower
        and close
    )
    report.record(
        "NL-to-SQL Accuracy", "WAC revenue excludes hub_dispense/market_data (paid demand only)",
        ok, question="What's our WAC revenue this month?", sql=body.get("sql"),
        expected=f"~{expected} (distributor, brand_flag=1, mo_offset=0 only)",
        actual=f"{actual} (full answer: {body.get('answer')!r})",
    )
    assert ok, body


# ---------------------------------------------------------------------------
# Issue 5 — "top accounts" with NO period named at all must not time out, even
# when the model forgets the prompt-level default-period instruction; the backend
# (sql_guard.ensure_default_period) is the backstop, not just the prompt.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("question", [
    "Who are our top 10 accounts by volume?",  # the exact live bug report
    "What are our top accounts?",
    "Who are our best customers?",
    "What are our biggest accounts by units?",
])
def test_no_period_account_questions_do_not_time_out(question, login, users, report):
    c = login(users["exec"])
    resp = c.post("/chat", json={"message": question, "show_sql": True})
    body = resp.json()
    ok = (
        resp.status_code == 200
        and body.get("row_count", 0) > 0
        and "error" not in body
    )
    report.record(
        "NL-to-SQL Accuracy", f"No-period account question: {question!r}", ok,
        question=question, sql=body.get("sql"),
        expected="succeeds (200, rows returned, no error) - backend enforces a "
                 "default period even if the model's own SQL doesn't filter by one",
        actual=f"status={resp.status_code} row_count={body.get('row_count')} "
               f"error={body.get('error')!r} answer={body.get('answer')!r}",
    )
    assert ok, body
