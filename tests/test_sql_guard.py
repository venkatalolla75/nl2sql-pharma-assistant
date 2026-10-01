"""Unit tests for the app-layer SQL validator (backend/app/sql_guard.py).

No DB or network needed — pure text-level checks. These cover the same threats the
database itself blocks (see test_db_security.py) as a fast first line of defense, plus
prompt-injection-style multi-statement attempts.
"""

import pytest

from app.sql_guard import (
    MAX_ROW_LIMIT,
    SqlValidationError,
    ensure_default_period,
    validate_and_finalize,
)


def test_simple_select_passes_and_gets_limit():
    sql = validate_and_finalize("SELECT 1", "exec")
    assert sql.startswith("SELECT 1")
    assert f"LIMIT {MAX_ROW_LIMIT}" in sql


def test_default_period_injected_when_sales_query_has_no_offset_filter():
    sql, defaulted = ensure_default_period(
        "SELECT COALESCE(o.grandparent_org_name, o.org_name) AS account_name, "
        "SUM(s.pack_units) AS total_volume FROM sales s "
        "JOIN organizations o ON s.org_id = o.org_id "
        "WHERE s.data_source = 'distributor' AND s.brand_flag = 1 "
        "GROUP BY account_name ORDER BY total_volume DESC LIMIT 10"
    )
    assert defaulted is True
    assert "s.mo_offset IN (0,1,2)" in sql
    # The original predicates must survive untouched, just with the filter prepended.
    assert "s.data_source = 'distributor'" in sql
    assert "GROUP BY account_name ORDER BY total_volume DESC LIMIT 10" in sql


def test_default_period_not_injected_when_offset_already_present():
    original = "SELECT SUM(pack_units) FROM sales WHERE mo_offset = 0"
    sql, defaulted = ensure_default_period(original)
    assert defaulted is False
    assert sql == original


def test_default_period_not_injected_when_query_has_no_where_clause():
    sql, defaulted = ensure_default_period("SELECT SUM(pack_units) FROM sales LIMIT 500")
    assert defaulted is True
    assert "mo_offset IN (0,1,2)" in sql
    assert "LIMIT 500" in sql


def test_default_period_not_injected_for_non_sales_tables():
    original = "SELECT * FROM products WHERE brand_flag = 1"
    sql, defaulted = ensure_default_period(original)
    assert defaulted is False
    assert sql == original


def test_default_period_unaliased_sales_gets_unqualified_filter():
    sql, defaulted = ensure_default_period(
        "SELECT COUNT(*) FROM sales WHERE data_source = 'distributor'"
    )
    assert defaulted is True
    assert "mo_offset IN (0,1,2)" in sql
    assert "s.mo_offset" not in sql  # no alias to qualify with


def test_default_period_wk_offset_also_counts_as_already_scoped():
    original = "SELECT SUM(pack_units) FROM sales WHERE wk_offset = 0"
    sql, defaulted = ensure_default_period(original)
    assert defaulted is False
    assert sql == original


def test_default_period_applies_symmetrically_to_every_where_clause():
    """Regression test: an earlier version only injected into the FIRST WHERE clause,
    silently reintroducing the asymmetric-period market-share bug (R3M numerator vs.
    all-time denominator) that prompt engineering fixed last session."""
    sql, defaulted = ensure_default_period(
        "SELECT (SELECT SUM(s.pack_units) FROM sales s WHERE s.data_source = "
        "'distributor') / NULLIF((SELECT SUM(s2.pack_units) FROM sales s2 WHERE "
        "s2.data_source = 'market_data'), 0) AS market_share"
    )
    assert defaulted is True
    assert sql.count("mo_offset IN (0,1,2)") == 2
    assert "s.mo_offset IN (0,1,2)" in sql
    assert "s2.mo_offset IN (0,1,2)" in sql


def test_default_period_skips_where_clauses_not_scoping_sales():
    """A WHERE clause on a non-sales table (e.g. inside a CTE base query) must not get
    an offset filter it has no column for, even when a later scope does touch sales."""
    sql, defaulted = ensure_default_period(
        "WITH p AS (SELECT ndc FROM products WHERE brand_flag = 1) "
        "SELECT SUM(s.pack_units) FROM sales s JOIN p ON s.ndc = p.ndc "
        "WHERE s.data_source = 'distributor'"
    )
    assert defaulted is True
    assert "mo_offset" not in sql.split("WHERE brand_flag")[1].split(")")[0]
    assert "s.mo_offset IN (0,1,2)" in sql


def test_cte_with_select_allowed():
    sql = validate_and_finalize(
        "WITH t AS (SELECT 1 AS x) SELECT * FROM t", "exec"
    )
    assert sql.upper().startswith("WITH")


def test_existing_limit_not_duplicated():
    sql = validate_and_finalize("SELECT * FROM products LIMIT 10", "exec")
    assert sql.count("LIMIT") == 1
    assert "LIMIT 10" in sql


@pytest.mark.parametrize(
    "bad_sql",
    [
        "INSERT INTO sales (org_id) VALUES ('X')",
        "UPDATE sales SET wac = 0",
        "DELETE FROM sales",
        "DROP TABLE sales",
        "TRUNCATE sales",
        "ALTER TABLE sales ADD COLUMN x INT",
        "GRANT ALL ON sales TO PUBLIC",
        "CREATE TABLE evil (x INT)",
    ],
)
def test_rejects_write_and_ddl(bad_sql):
    with pytest.raises(SqlValidationError):
        validate_and_finalize(bad_sql, "exec")


def test_rejects_multiple_statements_prompt_injection_style():
    # A hostile/injected instruction trying to smuggle a second statement in after
    # a valid-looking SELECT must be rejected outright, regardless of role.
    with pytest.raises(SqlValidationError):
        validate_and_finalize("SELECT 1; DROP TABLE sales", "exec")


def test_rejects_users_table_reference():
    with pytest.raises(SqlValidationError):
        validate_and_finalize("SELECT * FROM users", "exec")


def test_rejects_pg_catalog_probe():
    with pytest.raises(SqlValidationError):
        validate_and_finalize("SELECT * FROM pg_catalog.pg_roles", "exec")


def test_rejects_information_schema_probe():
    with pytest.raises(SqlValidationError):
        validate_and_finalize(
            "SELECT table_name FROM information_schema.tables", "ram"
        )


@pytest.mark.parametrize("role", ["ram", "director"])
def test_rejects_wac_for_non_exec(role):
    with pytest.raises(SqlValidationError):
        validate_and_finalize("SELECT wac FROM sales", role)


@pytest.mark.parametrize("role", ["ram", "director"])
def test_rejects_wac_in_order_by_for_non_exec(role):
    with pytest.raises(SqlValidationError):
        validate_and_finalize(
            "SELECT org_id FROM sales ORDER BY wac DESC", role
        )


def test_allows_wac_for_exec():
    sql = validate_and_finalize("SELECT sum(wac) FROM sales", "exec")
    assert "wac" in sql.lower()


def test_non_select_first_word_rejected():
    with pytest.raises(SqlValidationError):
        validate_and_finalize("EXPLAIN SELECT 1", "exec")


def test_empty_sql_rejected():
    with pytest.raises(SqlValidationError):
        validate_and_finalize("   ", "exec")


# ---------------------------------------------------------------------------
# C1 (QA report, critical): set_config() inside a generated query let a RAM/Director
# override the session GUCs the OLD RLS policies trusted, reading any territory/region.
# The real fix is DB-level (db/02_security.sql: RLS now keyed on session_user via
# per-scope login roles, not a settable GUC at all — see test_db_security.py's
# test_c1_* tests, which prove the leak is closed even with sql_guard bypassed
# entirely). This block is the app-layer second line of defense: reject the attack
# before it ever reaches the database. All four payloads below are taken directly from
# the QA report (the literal "Example payload" SQL, plus the set_config/current_setting
# calls described in its table of confirmed bypasses).
# ---------------------------------------------------------------------------

QA_REPORT_C1_PAYLOADS = [
    # The report's own runnable "Example payload": leak Texas data as a New York RAM.
    "SELECT t.n FROM (SELECT set_config('app.current_territory','Texas',true) AS x) c "
    "CROSS JOIN LATERAL (SELECT count(*) AS n FROM sales WHERE c.x IS NOT NULL) t",
    # Escalate to director-of-West via set_config('app.current_role', ...).
    "SELECT t.n FROM (SELECT set_config('app.current_role','director',true), "
    "set_config('app.current_region','West',true) AS x) c "
    "CROSS JOIN LATERAL (SELECT count(*) AS n FROM sales WHERE c.x IS NOT NULL) t",
    # Loop all 15 territories in one query (report's third confirmed bypass variant).
    "SELECT zt.territory_name, (SELECT set_config('app.current_territory', "
    "zt.territory_name, true)), count(*) FROM sales s "
    "JOIN organizations o ON o.org_id = s.org_id "
    "JOIN zip_territory zt ON zt.zip = o.zip GROUP BY zt.territory_name",
    # current_setting() — set_config's "read sibling" the report explicitly calls out.
    "SELECT current_setting('app.current_territory')",
]


@pytest.mark.parametrize("attack_sql", QA_REPORT_C1_PAYLOADS)
def test_c1_qa_report_attack_payloads_rejected_as_ram(attack_sql):
    with pytest.raises(SqlValidationError):
        validate_and_finalize(attack_sql, "ram")


def test_c1_unicode_escaped_identifier_rejected():
    """A word-based filter alone can be bypassed by spelling a banned word via
    Postgres's Unicode-escape identifier/string syntax (U&"...") — the report flags
    this explicitly. No legitimate query over this schema needs it."""
    with pytest.raises(SqlValidationError):
        validate_and_finalize(
            "SELECT 1 FROM sales WHERE U&'\\0073et_config' = 1", "ram"
        )


def test_set_and_reset_keywords_rejected():
    with pytest.raises(SqlValidationError):
        validate_and_finalize("SELECT 1 FROM sales WHERE 1=1 AND set = 1", "ram")
    with pytest.raises(SqlValidationError):
        validate_and_finalize("SELECT 1 FROM sales WHERE 1=1 AND reset = 1", "ram")


def test_legitimate_query_not_blocked_by_c1_guards():
    """The new checks must not false-positive on ordinary column/table names — in
    particular 'offset' must not trip the set/reset keyword check."""
    sql = validate_and_finalize(
        "SELECT COALESCE(o.grandparent_org_name, o.org_name) AS account_name, "
        "SUM(s.pack_units) AS total_units FROM sales s "
        "JOIN organizations o ON s.org_id = o.org_id "
        "WHERE s.data_source = 'distributor' AND s.brand_flag = 1 "
        "AND s.mo_offset IN (0,1,2) GROUP BY account_name ORDER BY total_units DESC",
        "ram",
    )
    assert "mo_offset" in sql
