"""
Application-layer SQL validation — the SECOND line of defense.

The database itself is the primary enforcement point (RLS + column grants in
db/02_security.sql): even if every check here were skipped, a non-exec role physically
cannot select `wac` or rows outside its territory/region, and app_exec/app_director/
app_ram are never granted access to `users` at all. This module exists to reject
obviously wrong or hostile SQL *before* it reaches the database — cheap, fast, and turns
"permission denied" 500s into friendly chat responses — and to catch prompt-injection
attempts that try to get the LLM to emit DDL/DML rather than a SELECT.
"""

import re

MAX_ROW_LIMIT = 500

_FORBIDDEN_KEYWORDS = re.compile(
    r"\b("
    r"insert|update|delete|drop|alter|truncate|grant|revoke|create|"
    r"exec|execute|call|copy|vacuum|merge|attach|detach|pragma|"
    r"reindex|cluster|listen|notify|unlisten|refresh"
    r")\b",
    re.IGNORECASE,
)

_FORBIDDEN_TABLES = re.compile(
    r"\b(users|pg_catalog|pg_[a-z_]+|information_schema)\b", re.IGNORECASE
)

_WAC_COLUMN = re.compile(r"\bwac\b", re.IGNORECASE)

_LIMIT_CLAUSE = re.compile(r"\blimit\s+\d+\s*;?\s*$", re.IGNORECASE)

# --- Default time period enforcement ---------------------------------------------
# The prompt tells the model to default unscoped questions to R3M (last 3 months), but
# that's advisory — a model can simply forget, and "top accounts by volume" (no period
# named) has repeatedly done exactly that, scanning all 2M/3-years of sales and hitting
# the statement timeout. This is the backend backstop: if the generated SQL touches
# `sales` but never filters by an offset column anywhere, inject one. It's a text-level
# patch, not a SQL parser, but it handles multi-scope queries (a CTE plus a main query,
# or two subqueries like a market-share ratio's numerator/denominator) by treating each
# WHERE clause as its own scope — inject into EVERY WHERE whose immediately-preceding
# FROM/JOIN touches `sales` and whose own predicate list doesn't already have an offset
# filter. An earlier single-injection version only fixed the first WHERE, silently
# reintroducing the exact asymmetric-period bug (R3M numerator vs. all-time denominator)
# fixed by prompt engineering last session — caught by test_market_share_uses_distributor
# _over_market_data before this shipped; see the test for the two-subquery repro case.
DEFAULT_PERIOD_MO_OFFSETS = "0,1,2"  # R3M — must match periods.py's own R3M pattern

_SALES_TABLE = re.compile(r"\bsales\b", re.IGNORECASE)
_OFFSET_COLUMN = re.compile(r"\b(mo_offset|wk_offset)\b", re.IGNORECASE)
_SALES_ALIAS = re.compile(r"\bsales\s+(?:as\s+)?([a-zA-Z_]\w*)\b", re.IGNORECASE)
_WHERE_KEYWORD = re.compile(r"\bwhere\b", re.IGNORECASE)
_CLAUSE_BOUNDARY = re.compile(r"\b(group\s+by|order\s+by|limit)\b", re.IGNORECASE)
_SQL_KEYWORDS = {
    "where", "group", "order", "join", "on", "left", "right", "inner", "outer",
    "full", "cross", "limit", "union", "as", "and", "or", "select", "from",
}


def _period_filter_expr(scope_text: str) -> str:
    alias_match = _SALES_ALIAS.search(scope_text)
    alias = alias_match.group(1) if alias_match else None
    if alias and alias.lower() in _SQL_KEYWORDS:
        alias = None  # "FROM sales WHERE ..." - "where" isn't an alias
    return (
        f"{alias}.mo_offset IN ({DEFAULT_PERIOD_MO_OFFSETS})" if alias
        else f"mo_offset IN ({DEFAULT_PERIOD_MO_OFFSETS})"
    )


def ensure_default_period(sql: str) -> tuple[str, bool]:
    """Returns (sql, defaulted) - sql unchanged if nothing needed it; otherwise sql
    with a default `mo_offset IN (0,1,2)` filter injected into every WHERE clause that
    scopes a `sales` reference and doesn't already filter by an offset column, and
    defaulted=True, so the caller can make sure the answer states that a default period
    was applied.

    Known gap: a sales-touching scope that has NO WHERE clause of its own, while some
    OTHER scope earlier in the query does (e.g. a CTE base query filtering products),
    won't get a filter injected — inserting a brand-new WHERE clause at the right point
    for an arbitrary later scope needs real parsing, not regex. Hasn't shown up in any
    reported bug (every observed case has a WHERE on every sales-touching scope, or has
    none anywhere in the whole query, both of which this function handles), so not
    chased further; falls back to the prompt-level default same as before this existed.
    """
    if not _SALES_TABLE.search(sql):
        return sql, False

    wheres = list(_WHERE_KEYWORD.finditer(sql))

    if not wheres:
        if _OFFSET_COLUMN.search(sql):
            return sql, False
        filter_expr = _period_filter_expr(sql)
        boundary_match = _CLAUSE_BOUNDARY.search(sql)
        i = boundary_match.start() if boundary_match else len(sql)
        return f"{sql[:i]} WHERE {filter_expr} {sql[i:]}", True

    insertions = []  # (position, filter_expr), rightmost-first so offsets stay valid
    scope_start = 0
    for idx, wm in enumerate(wheres):
        before = sql[scope_start:wm.start()]  # this scope's FROM/JOIN clause(s)
        next_start = wheres[idx + 1].start() if idx + 1 < len(wheres) else len(sql)
        after = sql[wm.end():next_start]  # this WHERE's own predicate list
        if _SALES_TABLE.search(before) and not _OFFSET_COLUMN.search(after):
            insertions.append((wm.end(), _period_filter_expr(before)))
        scope_start = wm.end()

    if not insertions:
        return sql, False

    result = sql
    for pos, filter_expr in sorted(insertions, key=lambda x: -x[0]):
        result = f"{result[:pos]} {filter_expr} AND{result[pos:]}"
    return result, True


class SqlValidationError(Exception):
    def __init__(self, message: str, user_message: str):
        super().__init__(message)
        self.user_message = user_message


def validate_and_finalize(sql: str, role: str) -> str:
    """Raises SqlValidationError on any violation; otherwise returns SQL safe to execute,
    with a row limit appended if the model didn't include one."""
    cleaned = sql.strip().rstrip(";").strip()

    if not cleaned:
        raise SqlValidationError("empty SQL", "I couldn't turn that into a query.")

    # At most one statement — reject stacked/multiple statements outright.
    if ";" in cleaned:
        raise SqlValidationError(
            f"multiple statements: {cleaned!r}",
            "That request produced more than one SQL statement, which isn't allowed.",
        )

    first_word = re.match(r"\s*(\w+)", cleaned)
    first_word = first_word.group(1).lower() if first_word else ""
    if first_word not in ("select", "with"):
        raise SqlValidationError(
            f"not a SELECT: {cleaned!r}",
            "I can only run read-only SELECT queries, and that request wasn't one.",
        )

    if _FORBIDDEN_KEYWORDS.search(cleaned):
        raise SqlValidationError(
            f"forbidden keyword in: {cleaned!r}",
            "That request would modify data or schema, which I'm not allowed to do — "
            "I can only answer questions with read-only queries.",
        )

    if _FORBIDDEN_TABLES.search(cleaned):
        raise SqlValidationError(
            f"forbidden table reference in: {cleaned!r}",
            "That question touches data I don't have access to answer from.",
        )

    if role != "exec" and _WAC_COLUMN.search(cleaned):
        raise SqlValidationError(
            f"wac referenced by non-exec role {role}: {cleaned!r}",
            "Pricing (WAC) data isn't available at your access level. I can show you "
            "volume instead (pack units or equivalents) — want me to do that?",
        )

    if not _LIMIT_CLAUSE.search(cleaned):
        cleaned = f"{cleaned} LIMIT {MAX_ROW_LIMIT}"

    return cleaned
