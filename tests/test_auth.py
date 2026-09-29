"""Login/session tests — app-level auth, no LLM involved."""


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
