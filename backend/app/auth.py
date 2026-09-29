"""Login + session-backed user lookup.

The session cookie (signed via itsdangerous/Starlette SessionMiddleware) holds only the
user_id — never role/territory/WAC flag — so a client can't influence authorization by
tampering with session contents (and the cookie is signed anyway). Every request re-reads
the authoritative row from `users` via the unprivileged app_login connection.
"""

import bcrypt

from app.db import get_auth_connection


def authenticate(email: str, password: str) -> dict | None:
    with get_auth_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id, email, full_name, role, territory_name, region_name,
                       can_view_wac, password_hash
                FROM users WHERE email = %s
                """,
                (email.strip().lower(),),
            )
            row = cur.fetchone()

    if row is None:
        return None

    (user_id, db_email, full_name, role, territory_name, region_name,
     can_view_wac, password_hash) = row

    if not bcrypt.checkpw(password.encode(), password_hash.encode()):
        return None

    return {
        "user_id": user_id,
        "email": db_email,
        "full_name": full_name,
        "role": role,
        "territory_name": territory_name,
        "region_name": region_name,
        "can_view_wac": bool(can_view_wac),
    }


def get_user_by_id(user_id: str) -> dict | None:
    with get_auth_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id, email, full_name, role, territory_name, region_name,
                       can_view_wac
                FROM users WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()

    if row is None:
        return None

    (user_id, email, full_name, role, territory_name, region_name, can_view_wac) = row
    return {
        "user_id": user_id,
        "email": email,
        "full_name": full_name,
        "role": role,
        "territory_name": territory_name,
        "region_name": region_name,
        "can_view_wac": bool(can_view_wac),
    }
