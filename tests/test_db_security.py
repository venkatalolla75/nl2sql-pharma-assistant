"""
Database-level security tests — the PRIMARY control (RLS + column grants), exercised
directly through app.db.scoped_cursor with no LLM involved. These prove the access
control holds even if SQL generation or app.sql_guard were somehow bypassed.
"""

import pytest

from app.db import scoped_cursor

FULL_ORG_COUNT = 40000
FULL_SALES_COUNT = 2_000_000


def test_ram_scoped_to_single_territory():
    with scoped_cursor("ram", "New York Metro", "Northeast") as cur:
        cur.execute("SELECT count(*) FROM organizations")
        org_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM sales")
        sales_count = cur.fetchone()[0]
    assert 0 < org_count < FULL_ORG_COUNT
    assert 0 < sales_count < FULL_SALES_COUNT


def test_ram_sees_zero_rows_outside_own_territory():
    """Cross-territory leak check: every organization visible to this RAM must map
    back to their own territory via zip_territory (a table RAMs ARE granted, unlike
    org_scope) — proving RLS filtered rows before the query ever ran, not after."""
    with scoped_cursor("ram", "New York Metro", "Northeast") as cur:
        cur.execute(
            """
            SELECT count(*) FROM organizations o
            JOIN zip_territory zt ON zt.zip = o.zip
            WHERE zt.territory_name != 'New York Metro'
            """
        )
        leaked = cur.fetchone()[0]
    assert leaked == 0


def test_two_rams_in_same_region_see_different_scopes():
    with scoped_cursor("ram", "New York Metro", "Northeast") as cur:
        cur.execute("SELECT count(*) FROM organizations")
        ny_count = cur.fetchone()[0]
    with scoped_cursor("ram", "New England", "Northeast") as cur:
        cur.execute("SELECT count(*) FROM organizations")
        ne_count = cur.fetchone()[0]
    assert ny_count != ne_count  # different territories, different org sets
    assert ny_count > 0 and ne_count > 0


def test_director_sees_full_region_not_just_one_territory():
    with scoped_cursor("ram", "New York Metro", "Northeast") as cur:
        cur.execute("SELECT count(*) FROM organizations")
        ny_only = cur.fetchone()[0]
    with scoped_cursor("director", None, "Northeast") as cur:
        cur.execute("SELECT count(*) FROM organizations")
        region_total = cur.fetchone()[0]
    # Northeast region = New York Metro + New England territories combined
    assert region_total > ny_only


def test_director_cannot_see_other_regions():
    with scoped_cursor("director", None, "Northeast") as cur:
        cur.execute(
            """
            SELECT count(*) FROM organizations o
            JOIN zip_territory zt ON zt.zip = o.zip
            WHERE zt.region_name != 'Northeast'
            """
        )
        leaked = cur.fetchone()[0]
    assert leaked == 0


@pytest.mark.parametrize("role,territory,region", [
    ("ram", "New York Metro", "Northeast"),
    ("director", None, "Northeast"),
])
def test_wac_column_denied_at_db_level(role, territory, region):
    with scoped_cursor(role, territory, region) as cur:
        with pytest.raises(Exception, match="permission denied"):
            cur.execute("SELECT wac FROM sales LIMIT 1")


@pytest.mark.parametrize("role,territory,region", [
    ("ram", "New York Metro", "Northeast"),
    ("director", None, "Northeast"),
])
def test_select_star_denied_because_it_includes_wac(role, territory, region):
    """SELECT * must fail too, not just an explicit `wac` reference — otherwise a
    generated `SELECT * FROM sales` would silently leak pricing."""
    with scoped_cursor(role, territory, region) as cur:
        with pytest.raises(Exception, match="permission denied"):
            cur.execute("SELECT * FROM sales LIMIT 1")


def test_exec_sees_everything_and_full_wac():
    with scoped_cursor("exec", None, None) as cur:
        cur.execute("SELECT count(*) FROM organizations")
        assert cur.fetchone()[0] == FULL_ORG_COUNT
        cur.execute("SELECT count(*) FROM sales")
        assert cur.fetchone()[0] == FULL_SALES_COUNT
        cur.execute(
            "SELECT sum(wac) FROM sales WHERE data_source='distributor' AND brand_flag=1"
        )
        total = cur.fetchone()[0]
    assert total is not None and total > 0


@pytest.mark.parametrize("role,territory,region", [
    ("exec", None, None),
    ("director", None, "Northeast"),
    ("ram", "New York Metro", "Northeast"),
])
def test_users_table_unreachable_by_every_analytics_role(role, territory, region):
    """Even Exec's analytics role must never reach the auth table — login/auth uses a
    completely separate unprivileged connection path (app.auth), not app_exec/etc."""
    with scoped_cursor(role, territory, region) as cur:
        with pytest.raises(Exception, match="permission denied"):
            cur.execute("SELECT * FROM users LIMIT 1")


def test_reference_tables_unrestricted_for_every_role():
    for role, territory, region in [
        ("exec", None, None),
        ("director", None, "Northeast"),
        ("ram", "New York Metro", "Northeast"),
    ]:
        with scoped_cursor(role, territory, region) as cur:
            cur.execute("SELECT count(*) FROM products")
            assert cur.fetchone()[0] == 40
            cur.execute("SELECT count(*) FROM zip_territory")
            assert cur.fetchone()[0] > 0


# ---------------------------------------------------------------------------
# C1 (QA report, critical): confirms the fix at the layer that actually matters — these
# run the report's attack payloads directly through scoped_cursor, with no sql_guard
# involved at all, proving the leak is closed by *which role the connection
# authenticated as* (RLS keyed on session_user — db/02_security.sql), not by the
# app-layer word-blocklist in sql_guard.py (test_sql_guard.py's test_c1_* tests cover
# that second, independent layer). Reference values match the QA report exactly: New
# York Metro RAM sees 136,921 rows; Texas alone has 8,736; West region has 39,072.
# ---------------------------------------------------------------------------

def test_c1_set_config_cannot_leak_another_territory():
    """QA report's literal 'Example payload', run raw against the DB."""
    with scoped_cursor("ram", "New York Metro", "Northeast") as cur:
        cur.execute("SELECT count(*) FROM sales")
        baseline = cur.fetchone()[0]
        cur.execute(
            "SELECT t.n FROM (SELECT set_config('app.current_territory','Texas',true) "
            "AS x) c CROSS JOIN LATERAL (SELECT count(*) AS n FROM sales "
            "WHERE c.x IS NOT NULL) t"
        )
        attacked = cur.fetchone()[0]
    assert baseline == 136_921
    assert attacked == baseline  # must NOT be Texas's 8,736


def test_c1_set_config_cannot_escalate_to_director_of_another_region():
    with scoped_cursor("ram", "New York Metro", "Northeast") as cur:
        cur.execute("SELECT count(*) FROM sales")
        baseline = cur.fetchone()[0]
        cur.execute(
            "SELECT t.n FROM (SELECT set_config('app.current_role','director',true), "
            "set_config('app.current_region','West',true) AS x) c "
            "CROSS JOIN LATERAL (SELECT count(*) AS n FROM sales "
            "WHERE c.x IS NOT NULL) t"
        )
        attacked = cur.fetchone()[0]
    assert attacked == baseline  # must NOT be West region's 39,072


def test_c1_looping_all_territories_only_ever_shows_own_scope():
    with scoped_cursor("ram", "New York Metro", "Northeast") as cur:
        cur.execute(
            "SELECT zt.territory_name, "
            "(SELECT set_config('app.current_territory', zt.territory_name, true)), "
            "count(*) FROM sales s "
            "JOIN organizations o ON o.org_id = s.org_id "
            "JOIN zip_territory zt ON zt.zip = o.zip GROUP BY zt.territory_name"
        )
        rows = cur.fetchall()
    assert [r[0] for r in rows] == ["New York Metro"]  # every other territory: 0 rows
    assert rows[0][2] == 136_921


def test_c1_set_config_no_effect_even_run_before_any_real_query():
    """Belt and suspenders: attempt the override as the very first statement in the
    transaction, before org_in_scope's usual query shape, in case ordering mattered."""
    with scoped_cursor("ram", "New York Metro", "Northeast") as cur:
        cur.execute("SELECT set_config('app.current_territory', 'Texas', true)")
        cur.execute("SELECT count(*) FROM sales")
        assert cur.fetchone()[0] == 136_921
