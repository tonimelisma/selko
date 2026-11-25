"""The /auth routes (E20-E23) over a real SQLite database."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from selko.api.limits import limiter, password_attempts
from selko.api.routes import auth
from selko.services.accounts import TokenKeys

ORIGIN = "https://selkoapp.test"


@pytest.fixture
def client(db):
    limiter.reset()
    password_attempts.reset()
    app = FastAPI()
    app.state.db = db
    app.state.token_keys = TokenKeys(current="k" * 40)
    app.state.allowed_origins = [ORIGIN]
    app.state.environment = "production"
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(auth.router)
    with TestClient(app, base_url="https://api.selkoapp.test", headers={"Origin": ORIGIN}) as c:
        yield c


def _signup(client, email="sam@example.test", password="secret-pw"):
    return client.post("/auth/signup", json={"email": email, "password": password})


def _login(client, email="sam@example.test", password="secret-pw"):
    return client.post("/auth/token", json={"grant_type": "password", "email": email, "password": password})


def test_sign_up_then_sign_in(client):
    created = _signup(client)
    assert created.status_code == 201, created.text
    assert created.json()["user"]["email"] == "sam@example.test"
    login = _login(client)
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 3600
    cookie = login.headers["set-cookie"]
    for part in ("selko_refresh=", "HttpOnly", "Path=/auth", "SameSite=strict", "Secure"):
        assert part.lower() in cookie.lower(), cookie
    me = client.get("/auth/user", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == "sam@example.test"


def test_refresh_comes_from_the_cookie_only(client):
    _signup(client)
    _login(client)
    refreshed = client.post("/auth/token", json={"grant_type": "refresh_token"})
    assert refreshed.status_code == 200, refreshed.text
    assert "selko_refresh=" in refreshed.headers["set-cookie"]
    client.cookies.clear()
    refused = client.post("/auth/token", json={"grant_type": "refresh_token"})
    assert refused.status_code == 401


def test_wrong_password_is_400_with_gotrue_wording(client):
    _signup(client)
    login = _login(client, password="wrong-pw")
    assert login.status_code == 400
    assert login.json()["detail"]["message"] == "Invalid login credentials"
    assert "set-cookie" not in login.headers


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.test"}, {"Origin": ""}])
def test_cookie_endpoints_refuse_other_origins(client, headers):
    assert client.post("/auth/signup", json={"email": "a@b.test", "password": "secret-pw"}, headers=headers).status_code == 403
    assert client.post("/auth/token", json={"grant_type": "refresh_token"}, headers=headers).status_code == 403


@pytest.mark.parametrize("content_type", ["application/x-www-form-urlencoded", "text/plain"])
def test_cookie_endpoints_refuse_bodies_a_form_can_send(client, content_type):
    """A cross-site form (or no-preflight fetch) cannot reach the cookie endpoints, even with a JSON body."""
    _signup(client)
    response = client.post(
        "/auth/token",
        content='{"grant_type":"password","email":"sam@example.test","password":"secret-pw"}',
        headers={"Content-Type": content_type},
    )
    assert response.status_code in (415, 422)
    assert "set-cookie" not in response.headers


def test_logout_revokes_and_clears_the_cookie(client):
    _signup(client)
    access = _login(client).json()["access_token"]
    out = client.post("/auth/logout", json={"scope": "global"}, headers={"Authorization": f"Bearer {access}"})
    assert out.status_code == 204
    assert 'selko_refresh=""' in out.headers["set-cookie"] or "Max-Age=0" in out.headers["set-cookie"]
    client.cookies.clear()
    assert client.post("/auth/token", json={"grant_type": "refresh_token"}).status_code == 401


def test_logout_with_only_the_cookie_still_signs_out(client):
    _signup(client)
    _login(client)
    assert client.post("/auth/logout", json={"scope": "local"}).status_code == 204
    client.cookies.clear()
    assert client.post("/auth/token", json={"grant_type": "refresh_token"}).status_code == 401


def test_user_endpoint_needs_a_valid_token(client):
    assert client.get("/auth/user").status_code == 401
    assert client.get("/auth/user", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_password_sign_in_is_rate_limited(client):
    _signup(client)
    codes = [_login(client, password="wrong-pw").status_code for _ in range(11)]
    assert codes[:10] == [400] * 10 and codes[10] == 429


def test_refresh_is_not_held_to_the_password_rate(client):
    """Refreshes share the route but not the 10/minute sign-in budget."""
    _signup(client)
    assert _login(client).status_code == 200
    for _ in range(9):
        _login(client, password="wrong-pw")
    codes = [client.post("/auth/token", json={"grant_type": "refresh_token"}).status_code for _ in range(15)]
    assert codes == [200] * 15
    assert _login(client).status_code == 429  # the password budget is spent


def test_the_route_still_caps_refreshes(client):
    _signup(client)
    _login(client)
    codes = [client.post("/auth/token", json={"grant_type": "refresh_token"}).status_code for _ in range(30)]
    assert codes[-1] == 429 and 429 not in codes[:28]
