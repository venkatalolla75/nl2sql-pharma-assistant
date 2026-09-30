"""
Scoped Postgres access.

Every analytics query runs inside a short transaction that:
  1. connects as app_login (no privileges of its own — see db/02_security.sql)
  2. SET LOCAL ROLE app_exec | app_director | app_ram   (column-level WAC enforcement)
  3. SET LOCAL app.current_role / app.current_territory / app.current_region
     (row-level security scoping — see org_in_scope() in db/02_security.sql)
  4. SET LOCAL statement_timeout                         (defense against runaway queries)

The role and scope values come from the authenticated user's row in `users`, never from
the LLM or the request body — a malicious or confused generated query cannot widen its
own scope.
"""

import os
from contextlib import contextmanager

import psycopg

STATEMENT_TIMEOUT_MS = int(os.environ.get("STATEMENT_TIMEOUT_MS", "20000"))


def _conninfo() -> str:
    host = os.environ["POSTGRES_HOST"]
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = os.environ["POSTGRES_DB"]
    user = os.environ.get("APP_DB_USER", "app_login")
    password = os.environ["APP_DB_PASSWORD"]
    return f"host={host} port={port} dbname={dbname} user={user} password={password}"


def get_auth_connection() -> psycopg.Connection:
    """Plain app_login connection for the login flow (SELECT on users only)."""
    return psycopg.connect(_conninfo())


@contextmanager
def scoped_cursor(role: str, territory_name: str | None, region_name: str | None):
    """
    Yields a cursor scoped to the given role/territory/region for the duration of one
    transaction. `role` must be one of 'exec' | 'director' | 'ram'.
    """
    if role not in ("exec", "director", "ram"):
        raise ValueError(f"invalid role: {role!r}")

    # `role` is checked against a fixed whitelist above and `STATEMENT_TIMEOUT_MS` comes
    # from our own env config, so direct interpolation here is safe (SET does not accept
    # bind parameters for identifiers/literals in all PG versions). The GUC values below
    # are user-influenced (territory/region names), so those go through set_config(),
    # which — being an ordinary function call — accepts normal query parameters.
    pg_role = f"app_{role}"
    with psycopg.connect(_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL ROLE {pg_role}")
            cur.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
            cur.execute("SELECT set_config('app.current_role', %s, true)", (role,))
            cur.execute(
                "SELECT set_config('app.current_territory', %s, true)",
                (territory_name or "",),
            )
            cur.execute(
                "SELECT set_config('app.current_region', %s, true)",
                (region_name or "",),
            )
            yield cur
        conn.rollback()  # read-only queries; never persist anything from this path
