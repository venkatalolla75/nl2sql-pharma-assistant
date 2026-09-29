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
