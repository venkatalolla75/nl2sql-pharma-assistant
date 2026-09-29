import os
import re
import secrets

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from app import bedrock
from app.auth import authenticate, get_user_by_id
from app.db import scoped_cursor
from app.sql_guard import SqlValidationError, validate_and_finalize

app = FastAPI(title="NovaPharma NL-to-SQL Assistant")

SESSION_SECRET = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

MAX_HISTORY_TURNS = 6  # user+assistant pairs kept per conversation
# In-memory only — acceptable for a take-home demo; a production build would move this
# to Redis/DB-backed session storage so it survives restarts and multiple app instances.
_conversations: dict[str, list[dict]] = {}

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

    if raw_sql.upper().startswith("NO_QUERY"):
        reason = raw_sql.split(":", 1)[1].strip() if ":" in raw_sql else \
            "I don't have the data to answer that."
        answer = f"I'm not able to answer that from the data available to me — {reason}"
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})
        del history[: max(0, len(history) - 2 * MAX_HISTORY_TURNS)]
        return {"answer": answer, "sql": None, "columns": [], "rows": [], "row_count": 0}

    try:
        final_sql = validate_and_finalize(raw_sql, user["role"])
    except SqlValidationError as exc:
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": exc.user_message})
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
    except Exception as exc:
        friendly = (
            "I wasn't able to run that query — it may have asked for data outside "
            "your access level. Try rephrasing, or ask for a volume-based figure "
            "instead of dollars."
        )
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": friendly})
        del history[: max(0, len(history) - 2 * MAX_HISTORY_TURNS)]
        return JSONResponse(
            {"answer": friendly, "sql": final_sql if body.show_sql else None,
             "columns": [], "rows": [], "row_count": 0, "error": str(exc)},
            status_code=200,
        )

    row_count = len(rows)
    access_note = _access_note(user["role"], question)

    try:
        answer = bedrock.generate_answer(
            question, final_sql, columns, [list(r) for r in rows], access_note, row_count
        )
    except Exception:
        answer = (
            f"Query returned {row_count} row(s)."
            + (f" Note: {access_note}." if access_note else "")
        )

    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": f"[SQL: {final_sql}]\n{answer}"})
    del history[: max(0, len(history) - 2 * MAX_HISTORY_TURNS)]

    return {
        "answer": answer,
        "sql": final_sql if body.show_sql else None,
        "columns": columns,
        "rows": [list(r) for r in rows[:200]],
        "row_count": row_count,
    }
