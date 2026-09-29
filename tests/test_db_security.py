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
