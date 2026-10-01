"""
Translates mo_offset/wk_offset filters found in generated SQL into accurate,
human-readable period descriptions for the answer step.

Offset -> calendar-label mappings are computed once from the actual data (cached for the
process lifetime, since the dataset doesn't change at runtime) rather than guessed by the
LLM — the whole point is that the answer step should state the real period covered, never
a hallucinated one. See docs/period_offsets.md for the offset semantics this mirrors.
"""

import calendar
import re
from datetime import date

from app.db import scoped_cursor

_MO_CACHE: dict[int, str] | None = None
_WK_CACHE: dict[int, str] | None = None


def _mo_labels() -> dict[int, str]:
    global _MO_CACHE
    if _MO_CACHE is None:
        with scoped_cursor("exec", None, None) as cur:
            cur.execute("SELECT DISTINCT mo_offset, period_mo FROM sales")
            _MO_CACHE = {row[0]: row[1] for row in cur.fetchall()}
    return _MO_CACHE


def _wk_labels() -> dict[int, str]:
    global _WK_CACHE
    if _WK_CACHE is None:
        with scoped_cursor("exec", None, None) as cur:
            cur.execute("SELECT DISTINCT wk_offset, period_wk FROM sales")
            _WK_CACHE = {row[0]: row[1] for row in cur.fetchall()}
    return _WK_CACHE


def _month_bounds(period_mo: str) -> tuple[date, date]:
    year, month = (int(x) for x in period_mo.split("-"))
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _fmt(d: date) -> str:
    return d.strftime("%b %-d, %Y")


def _mo_range_label(offsets: list[int]) -> str | None:
    labels = _mo_labels()
    months = sorted({labels[o] for o in offsets if o in labels})
    if not months:
        return None
    start, _ = _month_bounds(months[0])
    _, end = _month_bounds(months[-1])
    span = f"{_fmt(start)} - {_fmt(end)}"
    if len(months) == 1:
        return f"{months[0]} ({span})"
    return f"{months[0]} to {months[-1]} ({span})"


# Mirrors docs/period_offsets.md's "Common Time Windows" table exactly.
_MO_PATTERNS: list[tuple[re.Pattern, list[int], str]] = [
    (re.compile(r"\bmo_offset\s*=\s*0\b"), [0], "the current month"),
    (re.compile(r"\bmo_offset\s*=\s*1\b"), [1], "last month"),
    (re.compile(r"\bmo_offset\s+in\s*\(\s*0\s*,\s*1\s*,\s*2\s*\)", re.I),
     [0, 1, 2], "the last 3 months (R3M)"),
    (re.compile(r"\bmo_offset\s+in\s*\(\s*3\s*,\s*4\s*,\s*5\s*\)", re.I),
     [3, 4, 5], "the prior 3 months (R6M comparison window)"),
    (re.compile(r"\bmo_offset\s+in\s*\(\s*1\s*,\s*2\s*,\s*3\s*\)", re.I),
     [1, 2, 3], "last quarter"),
    (re.compile(r"\bmo_offset\s+between\s+0\s+and\s+5\b", re.I),
     [0, 1, 2, 3, 4, 5], "the last 6 months"),
]

_WK_PATTERNS: list[tuple[re.Pattern, list[int], str]] = [
    (re.compile(r"\bwk_offset\s*=\s*0\b"), [0], "the current week"),
    (re.compile(r"\bwk_offset\s*<=\s*3\b"), [0, 1, 2, 3], "the last 4 weeks (R30D)"),
]

# QA report (H2): "this year"/YTD was defined as mo_offset BETWEEN 0 AND 11 (a trailing
# 12-month window), then the answer step called it "January to November" regardless of
# what months were actually in the data (data ends Sep 2026) - neither the filter nor the
# label was actually year-to-date. prompts.py rule 5 now has the model emit this exact
# period_mo subquery shape for "this year"/YTD instead; matching it here lets the answer
# state the REAL calendar year and REAL month range from the data, never a guessed one.
_YTD_PATTERN = re.compile(
    r"period_mo\s*>=\s*\(\s*select\s+left\s*\(\s*period_mo\s*,\s*4\s*\)\s*\|\|\s*'-01'"
    r"\s+from\s+sales\s+where\s+mo_offset\s*=\s*0",
    re.IGNORECASE,
)


def _ytd_label() -> str | None:
    labels = _mo_labels()
    current = labels.get(0)
    if not current:
        return None
    year = current.split("-")[0]
    months = sorted({m for m in labels.values() if m.startswith(f"{year}-")})
    if not months:
        return None
    start, _ = _month_bounds(months[0])
    _, end = _month_bounds(months[-1])
    span = f"{_fmt(start)} - {_fmt(end)}"
    if len(months) == 1:
        return f"year to date ({year}): {months[0]} ({span})"
    return f"year to date ({year}): {months[0]} to {months[-1]} ({span})"


def period_note(sql: str) -> str | None:
    """Best-effort, data-grounded period description for the query that just ran, to
    feed generate_answer() so it states the real period instead of guessing or omitting
    it. Returns None if no recognized offset filter is present — not every question is
    period-bound (e.g. "list our branded products"), and we'd rather say nothing than
    guess."""
    if _YTD_PATTERN.search(sql):
        label = _ytd_label()
        if label:
            return f"the period covered is {label}"

    for pattern, offsets, label in _MO_PATTERNS:
        if pattern.search(sql):
            range_label = _mo_range_label(offsets)
            if range_label:
                return f"the period covered is {label}: {range_label}"
            return f"the period covered is {label}"

    for pattern, offsets, label in _WK_PATTERNS:
        if pattern.search(sql):
            labels = _wk_labels()
            weeks = sorted({labels[o] for o in offsets if o in labels})
            if not weeks:
                return f"the period covered is {label}"
            span = weeks[0] if len(weeks) == 1 else f"{weeks[0]} to {weeks[-1]}"
            return f"the period covered is {label} ({span})"

    return None
