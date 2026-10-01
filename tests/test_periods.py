"""
H2 (QA report, high): "this year"/YTD was defined as mo_offset BETWEEN 0 AND 11 (a
trailing 12-month window spanning two calendar years), and the answer text then called it
"January to November" regardless of what the data actually covered. These tests exercise
app.periods.period_note's new YTD recognition directly against the local DB's real
period_mo values — no Bedrock/network needed.
"""

from app.periods import period_note

YTD_SQL = (
    "SELECT SUM(s.pack_units) AS total_units FROM sales s WHERE s.data_source = "
    "'distributor' AND s.brand_flag = 1 AND s.period_mo >= (SELECT LEFT(period_mo, 4) "
    "|| '-01' FROM sales WHERE mo_offset = 0 LIMIT 1)"
)


def test_ytd_pattern_recognized_and_labeled_from_real_data():
    """Known data: mo_offset=0 is period_mo '2026-09' (QA report: 'data ends Sep 2026') -
    so year-to-date must be labeled 2026, Jan-Sep, never a hardcoded 'January to
    November' (the exact wrong label the report caught in the live app)."""
    note = period_note(YTD_SQL)
    assert note is not None
    assert "year to date" in note.lower()
    assert "2026" in note
    assert "january to november" not in note.lower()


def test_ytd_pattern_not_confused_with_trailing_12_months():
    trailing_12mo_sql = (
        "SELECT SUM(pack_units) FROM sales WHERE mo_offset BETWEEN 0 AND 11"
    )
    note = period_note(trailing_12mo_sql)
    # Still recognized (existing BETWEEN pattern unaffected), but must NOT be mislabeled
    # as "year to date" - it's a different, 12-months-regardless-of-calendar window.
    assert note is None or "year to date" not in note.lower()


def test_ytd_pattern_case_and_whitespace_insensitive():
    variant = YTD_SQL.replace("SELECT LEFT", "select left").replace(
        "period_mo, 4", "period_mo,4"
    )
    note = period_note(variant)
    assert note is not None
    assert "year to date" in note.lower()
