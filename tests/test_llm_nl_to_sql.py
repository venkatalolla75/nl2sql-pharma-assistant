"""
NL-to-SQL accuracy tests. For each question, an independently hand-written SQL query
(matching the domain rules in docs/) computes the expected value directly via
app.db.scoped_cursor, then the same question is asked through the real /chat endpoint
(full pipeline: Bedrock SQL generation -> validation -> scoped execution -> NL answer),
and the two are compared. This tests actual model behavior, not a mocked one.

Requires AWS credentials with Bedrock access (skipped otherwise — see conftest.py).
"""

import pytest

from app.db import scoped_cursor
from tests.conftest import requires_bedrock

pytestmark = requires_bedrock


def _first_number(rows):
    if not rows or not rows[0]:
        return None
    for v in rows[0]:
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _close(a, b, rel_tol=0.08):
    if a is None or b is None:
        return False
    if a == 0 and b == 0:
        return True
    return abs(a - b) <= rel_tol * max(abs(a), abs(b), 1)


def test_exec_total_volume_this_month(login, users, report):
    question = "What is our total sales volume in pack units this month?"
    with scoped_cursor("exec", None, None) as cur:
        cur.execute(
            "SELECT SUM(pack_units) FROM sales "
            "WHERE data_source='distributor' AND brand_flag=1 AND mo_offset=0"
        )
        expected = float(cur.fetchone()[0])

    c = login(users["exec"])
    resp = c.post("/chat", json={"message": question, "show_sql": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    actual = _first_number(body["rows"])

    ok = _close(actual, expected)
    report.record(
        "NL-to-SQL Accuracy", "Exec: total volume this month", ok,
        question=question, sql=body.get("sql"),
        expected=expected, actual=actual,
    )
    assert ok, f"expected ~{expected}, got {actual} (SQL: {body.get('sql')})"


def test_exec_hub_dispense_free_drug_excluded_from_default_volume(login, users, report):
    question = "How much free drug (hub dispense) did we provide for Cyclonova?"
    # No period named -> backend-enforced default (sql_guard.ensure_default_period)
    # applies R3M even when the model's own SQL doesn't filter by one; see TESTS.md's
    # "top accounts" timeout bug for why this is now enforced server-side, not just by
    # the prompt (and test_sql_guard.py for the injection logic itself).
    with scoped_cursor("exec", None, None) as cur:
        cur.execute(
            "SELECT SUM(pack_units) FROM sales "
            "WHERE data_source='hub_dispense' AND drug_name='CYCLONOVA' "
            "AND mo_offset IN (0,1,2)"
        )
        expected = float(cur.fetchone()[0] or 0)

    c = login(users["exec"])
    resp = c.post("/chat", json={"message": question, "show_sql": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    actual = _first_number(body["rows"])

    ok = _close(actual, expected)
    report.record(
        "NL-to-SQL Accuracy", "Exec: hub_dispense volume for Cyclonova", ok,
        question=question, sql=body.get("sql"),
        expected=expected, actual=actual,
        notes="Must use data_source='hub_dispense', not 'distributor'.",
    )
    assert ok, f"expected ~{expected}, got {actual} (SQL: {body.get('sql')})"


def test_market_share_uses_distributor_over_market_data(login, users, report):
    question = "What is our market share for Zenovax in the Docetaxel market?"
    # No period named -> backend-enforced default applies R3M to BOTH sides of the
    # ratio symmetrically (sql_guard.ensure_default_period handles every WHERE clause
    # independently specifically so numerator/denominator stay matched - an earlier,
    # simpler version of that function only patched the first WHERE, which would have
    # broken this exact case; see test_sql_guard.py's symmetric-injection test).
    with scoped_cursor("exec", None, None) as cur:
        cur.execute(
            """
            SELECT
              (SELECT SUM(s.pack_units * p.unit_conversion_factor)
               FROM sales s JOIN products p ON s.ndc = p.ndc
               WHERE s.data_source='distributor' AND s.brand_flag=1
                 AND p.market_subcategory='Docetaxel' AND s.mo_offset IN (0,1,2))
              /
              NULLIF((SELECT SUM(s.pack_units * p.unit_conversion_factor)
               FROM sales s JOIN products p ON s.ndc = p.ndc
               WHERE s.data_source='market_data'
                 AND p.market_subcategory='Docetaxel' AND s.mo_offset IN (0,1,2)), 0)
            """
        )
        expected = float(cur.fetchone()[0])

    c = login(users["exec"])
    resp = c.post("/chat", json={"message": question, "show_sql": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    actual = _first_number(body["rows"])

    ok = _close(actual, expected, rel_tol=0.15)
    report.record(
        "NL-to-SQL Accuracy", "Market share: Zenovax in Docetaxel", ok,
        question=question, sql=body.get("sql"),
        expected=f"{expected:.4f}", actual=actual,
        notes="Numerator=distributor/brand_flag=1, denominator=market_data, "
              "matched on market_subcategory='Docetaxel'.",
    )
    assert ok, f"expected ~{expected:.4f}, got {actual} (SQL: {body.get('sql')})"


def test_top_accounts_grandparent_rollup(login, users, report):
    question = "What are our top 5 accounts by pack units in the last 3 months?"
    with scoped_cursor("exec", None, None) as cur:
        cur.execute(
            """
            SELECT COALESCE(o.grandparent_org_name, o.org_name) AS account_name,
                   SUM(s.pack_units) AS total_units
            FROM sales s JOIN organizations o ON s.org_id = o.org_id
            WHERE s.data_source='distributor' AND s.brand_flag=1
              AND s.mo_offset IN (0,1,2)
            GROUP BY account_name ORDER BY total_units DESC LIMIT 5
            """
        )
        expected_top = cur.fetchall()[0]  # (account_name, total_units)

    c = login(users["exec"])
    resp = c.post("/chat", json={"message": question, "show_sql": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    actual_names = [row[0] for row in body["rows"]] if body["rows"] else []
    ok = expected_top[0] in actual_names
    report.record(
        "NL-to-SQL Accuracy", "Top 5 accounts by volume (R3M)", ok,
        question=question, sql=body.get("sql"),
        expected=f"top account should be '{expected_top[0]}'",
        actual=f"returned accounts: {actual_names}",
        notes="Checks grandparent-level rollup with COALESCE fallback per "
              "docs/metric_definitions.md.",
    )
    assert ok, f"expected top account '{expected_top[0]}' in {actual_names}"


def test_ram_revenue_question_returns_volume_not_dollars(login, users, report):
    """A RAM asking a revenue question should get a units-based answer, not dollars —
    per docs/security_model.md ('offer volume-based alternatives')."""
    question = "What are my total sales in dollars this month?"
    territory, region = "New York Metro", "Northeast"
    with scoped_cursor("ram", territory, region) as cur:
        cur.execute(
            "SELECT SUM(pack_units) FROM sales "
            "WHERE data_source='distributor' AND brand_flag=1 AND mo_offset=0"
        )
        expected_units = float(cur.fetchone()[0] or 0)

    c = login(users["ram_ny_metro"])
    resp = c.post("/chat", json={"message": question, "show_sql": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    sql_lower = (body.get("sql") or "").lower()
    no_wac_in_sql = "wac" not in sql_lower
    mentions_pricing_limit = any(
        kw in body["answer"].lower()
        for kw in ("pricing", "wac", "dollar", "volume", "unit")
    )
    ok = no_wac_in_sql and mentions_pricing_limit
    report.record(
        "NL-to-SQL Accuracy", "RAM revenue question -> volume alternative", ok,
        question=question, sql=body.get("sql"),
        expected=f"no wac in SQL; answer explains volume substitute "
                 f"(reference units ~{expected_units})",
        actual=body["answer"],
    )
    assert ok, f"SQL={body.get('sql')!r} answer={body['answer']!r}"


def test_multiturn_followup_refines_prior_query(login, users, report):
    c = login(users["exec"])
    q1 = "What are our top 5 accounts by pack units in the last 3 months?"
    r1 = c.post("/chat", json={"message": q1, "show_sql": True})
    assert r1.status_code == 200, r1.text
    b1 = r1.json()

    q2 = "Now just show me the top 3"
    r2 = c.post("/chat", json={"message": q2, "show_sql": True})
    assert r2.status_code == 200, r2.text
    b2 = r2.json()

    ok = 0 < b2["row_count"] <= 3
    report.record(
        "NL-to-SQL Accuracy", "Multi-turn follow-up (top 5 -> top 3)", ok,
        question=f"[turn 1] {q1}  ->  [turn 2] {q2}",
        sql=b2.get("sql"),
        expected="turn 2 returns <= 3 rows, refining turn 1's query",
        actual=f"turn 1 rows={b1['row_count']}, turn 2 rows={b2['row_count']}",
    )
    assert ok, f"turn 2 returned {b2['row_count']} rows, expected 1-3"
