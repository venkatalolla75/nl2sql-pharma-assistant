"""Unit tests for the app-layer SQL validator (backend/app/sql_guard.py).

No DB or network needed — pure text-level checks. These cover the same threats the
database itself blocks (see test_db_security.py) as a fast first line of defense, plus
prompt-injection-style multi-statement attempts.
"""

import pytest

from app.sql_guard import MAX_ROW_LIMIT, SqlValidationError, validate_and_finalize


def test_simple_select_passes_and_gets_limit():
    sql = validate_and_finalize("SELECT 1", "exec")
    assert sql.startswith("SELECT 1")
    assert f"LIMIT {MAX_ROW_LIMIT}" in sql


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
