"""Login/session tests — app-level auth, no LLM involved."""

from app.main import _docs_urls


def test_me_requires_auth(client):
    r = client.get("/me")
    assert r.status_code == 401


def test_chat_requires_auth(client):
    r = client.post("/chat", json={"message": "hello"})
    assert r.status_code == 401


def test_login_wrong_password_rejected(client, users):
    r = client.post(
        "/login",
        json={"email": users["exec"], "password": "definitely-not-the-password"},
    )
    assert r.status_code == 401


def test_login_unknown_email_rejected(client):
    r = client.post(
        "/login", json={"email": "nobody@novapharma.com", "password": "x"}
    )
    assert r.status_code == 401


def test_login_success_exposes_correct_role_and_scope(login, users):
    c = login(users["exec"])
    me = c.get("/me").json()["user"]
    assert me["role"] == "exec"
    assert me["can_view_wac"] is True

    c = login(users["director_northeast"])
    me = c.get("/me").json()["user"]
    assert me["role"] == "director"
    assert me["region_name"] == "Northeast"
    assert me["can_view_wac"] is False

    c = login(users["ram_ny_metro"])
    me = c.get("/me").json()["user"]
    assert me["role"] == "ram"
    assert me["territory_name"] == "New York Metro"
    assert me["can_view_wac"] is False


# ---------------------------------------------------------------------------
# L1 (QA report, low): /docs and /redoc must be disabled when APP_ENV=production, but
# left on for local dev (where this test container itself runs, confirming the default).
# ---------------------------------------------------------------------------

def test_docs_urls_disabled_in_production():
    assert _docs_urls("production") == (None, None, None)


def test_docs_urls_enabled_by_default():
    assert _docs_urls("development") == ("/docs", "/redoc", "/openapi.json")


def test_docs_reachable_in_this_dev_container(client):
    """This test container runs without APP_ENV=production (see docker-compose.yml) -
    confirms /docs stays on for local dev, matching _docs_urls' default."""
    r = client.get("/docs")
    assert r.status_code == 200


def test_logout_clears_session(login, users):
    c = login(users["exec"])
    assert c.get("/me").status_code == 200
    r = c.post("/logout")
    assert r.status_code == 200
    assert c.get("/me").status_code == 401


def test_login_response_never_includes_password_hash(login, users):
    c = login(users["ram_ny_metro"])
    body = c.get("/me").json()
    assert "password" not in str(body).lower()
