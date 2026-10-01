"""
Scoped Postgres access.

Every analytics query connects DIRECTLY as the Postgres LOGIN role matching the
authenticated user's scope:
  - exec                    -> app_exec (shared; BYPASSRLS, sees everything)
  - director, region R      -> app_director__<slug(R)>
  - ram, territory T        -> app_ram__<slug(T)>
These are real, separate login identities (see db/02_security.sql and
db/load_data.py's provision_scope_roles()) — not one shared role plus a session variable
set per-request. RLS policies check session_user, which is fixed by which role the
connection authenticated as and cannot be changed by anything the query itself does.

This replaced an earlier design that connected as a single shared app_login, then issued
`SET LOCAL ROLE app_director` and `SET LOCAL app.current_territory = ...` via
set_config() inside the request's own transaction. That GUC lived in the same session the
LLM-generated SQL executed in, and set_config() is an ordinary function — a generated
query could call it directly and override its own scope (a RAM reading another
territory's data; see db/02_security.sql's C1 design note for the full writeup, and
backend/app/sql_guard.py for the application-layer block on set_config/current_setting/
SET/RESET, which is defense in depth now, not the primary control). Connecting as a
distinct role per scope removes the mutable session state that bug depended on entirely.

The role and scope values come from the authenticated user's row in `users`, never from
the LLM or the request body — a malicious or confused generated query cannot change which
role this connects as (that decision is made in Python, before any query text exists).
"""

import os
import re
from contextlib import contextmanager

import psycopg

STATEMENT_TIMEOUT_MS = int(os.environ.get("STATEMENT_TIMEOUT_MS", "20000"))


def slugify(name: str) -> str:
    """'New York Metro' -> 'new_york_metro'. Must match db/load_data.py's copy exactly."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _conninfo(user: str, password: str) -> str:
    host = os.environ["POSTGRES_HOST"]
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = os.environ["POSTGRES_DB"]
    return f"host={host} port={port} dbname={dbname} user={user} password={password}"


def get_auth_connection() -> psycopg.Connection:
    """Plain app_login connection for the login flow (SELECT on users only) — unrelated
    to analytics access; app_login has no membership in app_exec/app_director/app_ram or
    any per-scope role, so it cannot read sales/organizations regardless."""
    user = os.environ.get("APP_DB_USER", "app_login")
    return psycopg.connect(_conninfo(user, os.environ["APP_DB_PASSWORD"]))


@contextmanager
def scoped_cursor(role: str, territory_name: str | None, region_name: str | None):
    """
    Yields a cursor connected as the Postgres login role matching role/territory/region,
    for the duration of one transaction. `role` must be one of 'exec' | 'director' | 'ram'.
    """
    if role == "exec":
        pg_role = "app_exec"
    elif role == "director":
        if not region_name:
            raise ValueError("director requires region_name")
        pg_role = f"app_director__{slugify(region_name)}"
    elif role == "ram":
        if not territory_name:
            raise ValueError("ram requires territory_name")
        pg_role = f"app_ram__{slugify(territory_name)}"
    else:
        raise ValueError(f"invalid role: {role!r}")

    password = os.environ["SCOPE_ROLE_PASSWORD"]
    with psycopg.connect(_conninfo(pg_role, password)) as conn:
        with conn.cursor() as cur:
            # Not a security control (that's session_user + RLS, fixed at connection
            # time above) — just a runaway-query guard, safe to leave settable.
            cur.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
            yield cur
        conn.rollback()  # read-only queries; never persist anything from this path
