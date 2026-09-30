"""
Per-user rate limit on /chat: 60 questions/hour, friendly 429 when exceeded.

The sliding-window logic (app.main._rate_limit_ok) is pure and needs neither Bedrock nor
a live deployment, so these run unconditionally (no requires_bedrock marker). The one
HTTP-level test monkeypatches the limiter directly rather than actually sending 60+ real
chat messages, and is skipped against a live deployment for the same reason the other
monkeypatch-based tests are (see test_answer_quality.py) — it only affects the
in-process app, not a remote server.
"""

from app import main as main_module
from tests.conftest import LIVE_URL


def test_rate_limit_allows_up_to_the_hourly_cap_then_blocks():
    uid = "test-rate-limit-cap"
    main_module._chat_request_times.pop(uid, None)
    for _ in range(main_module.RATE_LIMIT_PER_HOUR):
        assert main_module._rate_limit_ok(uid) is True
    assert main_module._rate_limit_ok(uid) is False


def test_rate_limit_resets_after_the_window_elapses(monkeypatch):
    uid = "test-rate-limit-window"
    main_module._chat_request_times.pop(uid, None)
    t = [1_000_000.0]
    monkeypatch.setattr(main_module.time, "monotonic", lambda: t[0])

    for _ in range(main_module.RATE_LIMIT_PER_HOUR):
        assert main_module._rate_limit_ok(uid) is True
    assert main_module._rate_limit_ok(uid) is False

    t[0] += main_module.RATE_LIMIT_WINDOW_SECONDS + 1
    assert main_module._rate_limit_ok(uid) is True


def test_rate_limit_is_per_user_not_global():
    uid_a, uid_b = "test-rate-limit-user-a", "test-rate-limit-user-b"
    main_module._chat_request_times.pop(uid_a, None)
    main_module._chat_request_times.pop(uid_b, None)
    for _ in range(main_module.RATE_LIMIT_PER_HOUR):
        assert main_module._rate_limit_ok(uid_a) is True
    assert main_module._rate_limit_ok(uid_a) is False
    assert main_module._rate_limit_ok(uid_b) is True  # untouched by user A's usage


def test_chat_returns_429_with_friendly_message_when_rate_limited(login, users, monkeypatch):
    if LIVE_URL:
        import pytest
        pytest.skip("monkeypatches app.main._rate_limit_ok in this process - only "
                    "affects the in-process app, not a remote deployed server")
    monkeypatch.setattr(main_module, "_rate_limit_ok", lambda _uid: False)

    c = login(users["exec"])
    resp = c.post("/chat", json={"message": "Anything.", "show_sql": True})
    body = resp.json()
    assert resp.status_code == 429
    assert "60" in body["answer"]
    assert body["sql"] is None
    assert body["row_count"] == 0
