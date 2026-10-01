import os
import re
import secrets
import time
from collections import deque

import psycopg
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from app import bedrock
from app.auth import authenticate, get_user_by_id
from app.db import scoped_cursor
from app.periods import period_note as _period_note
from app.sql_guard import (
    SqlValidationError,
    ensure_default_period,
    strip_no_period_marker,
    validate_and_finalize,
)

app = FastAPI(title="NovaPharma NL-to-SQL Assistant")

SESSION_SECRET = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

MAX_HISTORY_TURNS = 6  # user+assistant pairs kept per conversation
# In-memory only — acceptable for a take-home demo; a production build would move this
# to Redis/DB-backed session storage so it survives restarts and multiple app instances.
_conversations: dict[str, list[dict]] = {}

RATE_LIMIT_PER_HOUR = 60
RATE_LIMIT_WINDOW_SECONDS = 3600
# Per-user sliding window of request timestamps. In-memory, same caveat as
# _conversations above — caps both brute-force abuse of the shared demo login and
# per-user Bedrock spend. Keyed by user_id (not session), so it survives logout/login.
_chat_request_times: dict[str, deque] = {}


def _rate_limit_ok(user_id: str) -> bool:
    now = time.monotonic()
    window = _chat_request_times.setdefault(user_id, deque())
    while window and now - window[0] > RATE_LIMIT_WINDOW_SECONDS:
        window.popleft()
    if len(window) >= RATE_LIMIT_PER_HOUR:
        return False
    window.append(now)
    return True

_REVENUE_WORDS = re.compile(
    r"\b(revenue|dollars?|\$|price|pricing|wac|cost|profit)\b", re.IGNORECASE
)
_BROAD_SCOPE_WORDS = re.compile(
    r"\b(all territories|every territory|company-?wide|nationwide|"
    r"across the country|all regions)\b",
    re.IGNORECASE,
)


class LoginRequest(BaseModel):
    email: str
    password: str


class ChatRequest(BaseModel):
    message: str
    show_sql: bool = False


def _require_user(request: Request) -> dict:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    user = get_user_by_id(user_id)
    if user is None:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Session invalid")
    return user


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.post("/login")
def login(body: LoginRequest, request: Request):
    user = authenticate(body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    request.session["user_id"] = user["user_id"]
    _conversations.pop(user["user_id"], None)
    return {"ok": True, "user": _public_user(user)}


@app.post("/logout")
def logout(request: Request):
    user_id = request.session.get("user_id")
    if user_id:
        _conversations.pop(user_id, None)
    request.session.clear()
    return {"ok": True}


@app.get("/me")
def me(request: Request):
    user = _require_user(request)
    return {"user": _public_user(user)}


def _public_user(user: dict) -> dict:
    return {
        "full_name": user["full_name"],
        "email": user["email"],
        "role": user["role"],
        "territory_name": user["territory_name"],
        "region_name": user["region_name"],
        "can_view_wac": user["can_view_wac"],
    }


def _access_note(role: str, question: str) -> str | None:
    if role == "exec":
        return None
    notes = []
    if _REVENUE_WORDS.search(question):
        notes.append(
            "pricing/WAC data isn't available at this access level, so the figures "
            "below are unit-based (pack units), not dollars"
        )
    if _BROAD_SCOPE_WORDS.search(question):
        scope = "region" if role == "director" else "territory"
        notes.append(f"results are limited to the user's own {scope} only")
    return "; ".join(notes) if notes else None


@app.post("/chat")
def chat(body: ChatRequest, request: Request):
    user = _require_user(request)

    if not _rate_limit_ok(user["user_id"]):
        return JSONResponse(
            {"answer": f"You've reached the limit of {RATE_LIMIT_PER_HOUR} questions "
                       "per hour. Please try again a bit later.",
             "sql": None, "columns": [], "rows": [], "row_count": 0},
            status_code=429,
        )

    question = body.message.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Empty message")

    history = _conversations.setdefault(user["user_id"], [])

    try:
        raw_sql = bedrock.generate_sql(
            question=question,
            history=history,
            role=user["role"],
            full_name=user["full_name"],
            territory_name=user["territory_name"],
            region_name=user["region_name"],
        )
    except Exception as exc:  # Bedrock/network errors
        return JSONResponse(
            {"answer": "Sorry, I couldn't reach the language model right now. "
                       "Please try again in a moment.", "error": str(exc)},
            status_code=502,
        )

    # In every branch below, the assistant's history entry is always the raw/validated
    # SQL text the model produced for this turn — never a human-facing message. History
    # is replayed straight into the next generate_sql() call, and storing anything other
    # than SQL there caused weaker-instruction-following models to pattern-match and echo
    # that non-SQL shape back on the next turn (see commit history for the two bugs this
    # already caused: a mixed "[SQL: ...]\n{answer}" format, and a plain-English error
    # message), breaking follow-ups both times.
    if raw_sql.upper().startswith("NO_QUERY"):
        reason = raw_sql.split(":", 1)[1].strip() if ":" in raw_sql else \
            "I don't have the data to answer that."
        answer = f"I'm not able to answer that from the data available to me — {reason}"
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": raw_sql})
        del history[: max(0, len(history) - 2 * MAX_HISTORY_TURNS)]
        return {"answer": answer, "sql": None, "columns": [], "rows": [], "row_count": 0}

    try:
        # The model prepends a `-- NO_PERIOD` marker line when the user explicitly asked
        # for all-time/unscoped history (prompts.py rule 8) — strip it before validation
        # so it never reaches the database, and remember the signal for the backstop
        # below (see sql_guard.strip_no_period_marker's docstring for why this has to
        # come from the model rather than a post-hoc regex guess).
        sql_to_validate, force_no_period = strip_no_period_marker(raw_sql)
        final_sql = validate_and_finalize(sql_to_validate, user["role"])
        # Backend backstop, not just a prompt instruction: the model is told to default
        # unscoped questions to R3M, but has been observed simply not doing it (e.g.
        # "top accounts by volume" with no period named), scanning all 2M/3 years of
        # sales and hitting the statement timeout. If the validated SQL touches `sales`
        # but never filters by any period column (mo_offset/wk_offset/period_qtr/
        # period_mo/period_wk/transaction_date/week_ending_date), enforce the default
        # here — unless the model's own NO_PERIOD marker said this is intentional.
        # _period_note (below) picks up the injected filter automatically and tells
        # generate_answer to state the period, same as an LLM-written one would.
        final_sql, _ = ensure_default_period(final_sql, force_no_period=force_no_period)
    except SqlValidationError as exc:
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": raw_sql})
        del history[: max(0, len(history) - 2 * MAX_HISTORY_TURNS)]
        return {
            "answer": exc.user_message, "sql": raw_sql if body.show_sql else None,
            "columns": [], "rows": [], "row_count": 0,
        }

    try:
        with scoped_cursor(
            user["role"], user["territory_name"], user["region_name"]
        ) as cur:
            cur.execute(final_sql)
            columns = [d.name for d in cur.description] if cur.description else []
            rows = cur.fetchall() if cur.description else []
    except psycopg.errors.InsufficientPrivilege as exc:
        # The ONLY case where "outside your access level" is actually true: the DB
        # itself (column grants / RLS) denied this query. Every other DB failure below
        # gets a generic message instead — a prior bug always blamed "access level"
        # regardless of cause, which was flatly wrong for e.g. a statement timeout.
        friendly = (
            "I wasn't able to run that query — it asked for data outside your access "
            "level. Try rephrasing, or ask for a volume-based figure instead of dollars."
        )
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": final_sql})
        del history[: max(0, len(history) - 2 * MAX_HISTORY_TURNS)]
        return JSONResponse(
            {"answer": friendly, "sql": final_sql if body.show_sql else None,
             "columns": [], "rows": [], "row_count": 0, "error": str(exc)},
            status_code=200,
        )
    except Exception as exc:
        friendly = (
            "I wasn't able to run that query — it may have been too complex or slow "
            "for the current data volume. Try narrowing the time period or rephrasing "
            "your question."
        )
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": final_sql})
        del history[: max(0, len(history) - 2 * MAX_HISTORY_TURNS)]
        return JSONResponse(
            {"answer": friendly, "sql": final_sql if body.show_sql else None,
             "columns": [], "rows": [], "row_count": 0, "error": str(exc)},
            status_code=200,
        )

    row_count = len(rows)
    notes = [n for n in (_access_note(user["role"], question), _period_note(final_sql)) if n]
    combined_note = "; ".join(notes) if notes else None

    try:
        answer = bedrock.generate_answer(
            question, final_sql, columns, [list(r) for r in rows], combined_note, row_count
        )
    except Exception:
        answer = (
            f"Query returned {row_count} row(s)."
            + (f" Note: {combined_note}." if combined_note else "")
        )

    history.append({"role": "user", "content": question})
    # Store only the raw SQL here (not "[SQL: ...]\n{answer}") — this list is replayed
    # straight into the next generate_sql() call, and weaker-instruction-following models
    # (e.g. Nova) were found to pattern-match a mixed SQL+prose format from history and
    # echo that same hybrid shape back instead of raw SQL, tripping sql_guard's
    # SELECT-only check on the very next turn.
    history.append({"role": "assistant", "content": final_sql})
    del history[: max(0, len(history) - 2 * MAX_HISTORY_TURNS)]

    return {
        "answer": answer,
        "sql": final_sql if body.show_sql else None,
        "columns": columns,
        "rows": [list(r) for r in rows[:200]],
        "row_count": row_count,
    }
