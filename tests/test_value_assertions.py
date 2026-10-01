"""
Value-assertion tests (QA_REPORT.txt's core process-gap finding): every other test in
this suite checks SHAPE (status codes, row presence, access denial) — none of them
pinned down that the actual NUMBERS coming out of the full 2,000,000-row dataset are
right. That gap is exactly how C2 (period corruption) and H3 (market share off by 100x)
shipped and passed the existing suite. These tests hardcode the report's reference values
and check them directly against the database via app.db.scoped_cursor — DB-only, no
Bedrock/LLM involved, so they run even when Bedrock-dependent tests are skipped, and a
wrong number can never pass green again.

Reference values independently verified against the local full dataset before being
hardcoded here (see PLAN.md's QA_REPORT.txt remediation section for the verification
queries this was checked against).
"""

import pytest

from app.db import scoped_cursor

TOTAL_SALES_ROWS = 2_000_000
EXEC_ALLTIME_PAID_UNITS = 6_309_523
EXEC_ALLTIME_PAID_WAC = 3_242_848_648.11
NYM_R3M_PAID_UNITS = 35_689
NYM_R3M_PAID_TRANSACTIONS = 4_872
NYM_ALLTIME_VISIBLE_ROWS = 136_921
NORTHEAST_DIRECTOR_R3M_PAID_UNITS = 68_236
ZENOVAX_DOCETAXEL_R3M_MARKET_SHARE = 1.1378  # ~114%


def test_total_sales_rows_matches_full_dataset():
    with scoped_cursor("exec", None, None) as cur:
        cur.execute("SELECT count(*) FROM sales")
        assert cur.fetchone()[0] == TOTAL_SALES_ROWS


def test_exec_alltime_paid_demand_units_and_wac():
    with scoped_cursor("exec", None, None) as cur:
        cur.execute(
            "SELECT SUM(pack_units), SUM(wac) FROM sales "
            "WHERE data_source = 'distributor' AND brand_flag = 1"
        )
        units, wac = cur.fetchone()
    assert float(units) == pytest.approx(EXEC_ALLTIME_PAID_UNITS, abs=1)
    assert float(wac) == pytest.approx(EXEC_ALLTIME_PAID_WAC, abs=0.01)


def test_nym_ram_r3m_paid_units_and_transactions():
    with scoped_cursor("ram", "New York Metro", "Northeast") as cur:
        cur.execute(
            "SELECT SUM(pack_units), COUNT(*) FROM sales "
            "WHERE data_source = 'distributor' AND brand_flag = 1 "
            "AND mo_offset IN (0,1,2)"
        )
        units, txns = cur.fetchone()
    assert float(units) == pytest.approx(NYM_R3M_PAID_UNITS, abs=1)
    assert txns == NYM_R3M_PAID_TRANSACTIONS


def test_nym_ram_alltime_visible_row_count():
    """Also the C1 baseline (test_db_security.py's test_c1_* tests use this same
    number) - repeated here as an explicit value-assertion, not just a security check."""
    with scoped_cursor("ram", "New York Metro", "Northeast") as cur:
        cur.execute("SELECT count(*) FROM sales")
        assert cur.fetchone()[0] == NYM_ALLTIME_VISIBLE_ROWS


def test_northeast_director_r3m_paid_units():
    with scoped_cursor("director", None, "Northeast") as cur:
        cur.execute(
            "SELECT SUM(pack_units) FROM sales "
            "WHERE data_source = 'distributor' AND brand_flag = 1 "
            "AND mo_offset IN (0,1,2)"
        )
        units = cur.fetchone()[0]
    assert float(units) == pytest.approx(NORTHEAST_DIRECTOR_R3M_PAID_UNITS, abs=1)


def test_zenovax_docetaxel_r3m_market_share():
    """QA report's reference ~114% figure - a genuine property of the synthetic
    market_data (NovaPharma's Zenovax outsells the market_data estimate for its own
    subcategory in this period), not a bug. H3 covers the >100% display handling;
    this pins down the actual ratio so a regression there would also fail here."""
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
        share = float(cur.fetchone()[0])
    assert share == pytest.approx(ZENOVAX_DOCETAXEL_R3M_MARKET_SHARE, abs=0.001)
    assert share > 1.0  # >100% is the real, confirmed property under test here
