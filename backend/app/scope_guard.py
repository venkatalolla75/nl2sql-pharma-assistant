"""
Detects a question that names a territory or region outside the asking user's scope,
BEFORE any SQL is generated or run.

QA_REPORT.txt (H1): the database correctly returns 0 rows for an out-of-scope territory/
region (RLS), but the answer step then saw an empty result set with no indication of
*why* it was empty, and fabricated a plausible-sounding business explanation ("no sales
recorded ... due to market conditions") instead of saying access was denied. That both
misleads the user and leaks the fact that the named place exists while hiding the real
reason. Catching this here — on the question text, against the real territory/region
names — lets /chat short-circuit with an honest access message and an offer to run the
same question against the user's own scope, without spending an LLM call or a query on a
question that would always return nothing.
"""

import re

from app.db import scoped_cursor

_SCOPE_NAMES_CACHE: tuple[list[str], dict[str, str]] | None = None


def _scope_names() -> tuple[list[str], dict[str, str]]:
    """Returns (region_names, {territory_name: region_name}), cached for the process
    lifetime (the territory/region list is static reference data, like periods.py's
    offset-label caches)."""
    global _SCOPE_NAMES_CACHE
    if _SCOPE_NAMES_CACHE is None:
        with scoped_cursor("exec", None, None) as cur:
            cur.execute("SELECT DISTINCT territory_name, region_name FROM zip_territory")
            territory_region = {row[0]: row[1] for row in cur.fetchall()}
        regions = sorted(set(territory_region.values()))
        _SCOPE_NAMES_CACHE = (regions, territory_region)
    return _SCOPE_NAMES_CACHE


def _mentions(question_lower: str, name: str) -> bool:
    return re.search(rf"\b{re.escape(name.lower())}\b", question_lower) is not None


def find_out_of_scope_mention(
    question: str, role: str, territory_name: str | None, region_name: str | None
) -> str | None:
    """Returns a ready-to-show access message if the question names a territory/region
    the user's role doesn't have access to; otherwise None (nothing out of scope was
    named — including the common case of no place being named at all, which just
    proceeds through the normal pipeline as before).

    Exec has no restriction, so this never fires for role == "exec". A Director is
    scoped to their region (any territory within it is in scope); a RAM is scoped to
    their own single territory (their own region's NAME may still come up in casual
    phrasing — e.g. "how's my region doing" — and isn't itself a request for other
    territories' data, so it's allowed through unflagged)."""
    if role == "exec":
        return None

    regions, territory_region = _scope_names()
    question_lower = question.lower()

    for rname in regions:
        if rname == region_name:
            continue
        if _mentions(question_lower, rname):
            own = region_name if role == "director" else territory_name
            return (
                f"I don't have access to data for the {rname} region — I can only show "
                f"you results for {own}. Want me to run this for {own} instead?"
            )

    for tname, treg in territory_region.items():
        if role == "ram" and tname == territory_name:
            continue
        if role == "director" and treg == region_name:
            continue  # a territory within the Director's own region is in scope
        if _mentions(question_lower, tname):
            own = region_name if role == "director" else territory_name
            return (
                f"I don't have access to data for the {tname} territory — I can only "
                f"show you results for {own}. Want me to run this for {own} instead?"
            )

    return None
