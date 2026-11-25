"""GET /live over a real database and bus: who hears what, and when a stream ends."""

from __future__ import annotations

import json
import threading
import time

import httpx
import jwt
import pytest
import uvicorn
from fastapi import FastAPI

from selko.api.limits import limiter
from selko.api.routes import auth, live
from selko.services import accounts
from selko.services.accounts import TokenKeys

KEYS = TokenKeys(current="k" * 40)


@pytest.fixture
def app(db, monkeypatch):
    monkeypatch.setattr(live, "HEARTBEAT_SECONDS", 0.2)
    limiter.reset()
    application = FastAPI()
    application.state.db = db
    application.state.bus = db.bus
    application.state.token_keys = KEYS
    application.state.allowed_origins = ["https://selkoapp.test"]
    application.state.limiter = limiter
    application.include_router(auth.router)
    application.include_router(live.router)
    return application


@pytest.fixture
def client(app):
    """A real server: TestClient buffers whole bodies, and a live stream never ends."""
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as http:
        yield http
    server.should_exit = True
    thread.join(5)


def _token(db, email):
    accounts.sign_up(db, email, "secret-pw")
    return accounts.sign_in(db, KEYS, email, "secret-pw")


def _events(response, until, limit=60):
    """Parse SSE frames until ``until(events)`` is true or ``limit`` frames passed."""
    events, frame = [], []
    for line in response.iter_lines():
        if line == "":
            if frame:
                kind = next((f[7:] for f in frame if f.startswith("event: ")), "comment")
                data = next((json.loads(f[6:]) for f in frame if f.startswith("data: ")), None)
                events.append((kind, data))
                frame = []
                if until(events) or len(events) >= limit:
                    return events
            continue
        frame.append(line)
    return events


def _write_event(db, factory, user_id, delay=0.3):
    def go():
        time.sleep(delay)
        factory.event(user_id)

    threading.Thread(target=go, daemon=True).start()


def test_a_write_reaches_its_owner_once(client, app, db, factory):
    sam = _token(db, "sam@example.test")
    with client.stream(
        "GET", "/live", headers={"Authorization": f"Bearer {sam.access_token}"}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        _write_event(db, factory, sam.user["id"])
        events = _events(response, lambda ev: any(k == "invalidate" for k, _ in ev))
    assert events[0][0] == "ready"
    invalidations = [d for k, d in events if k == "invalidate"]
    assert invalidations[0]["resource"] == "events" and invalidations[0]["operation"] == "INSERT"


def test_another_users_write_is_never_heard(client, app, db, factory):
    sam = _token(db, "sam@example.test")
    alex = _token(db, "alex@example.test")
    with client.stream(
        "GET", "/live", headers={"Authorization": f"Bearer {sam.access_token}"}
    ) as response:
        _write_event(db, factory, alex.user["id"], delay=0.1)
        events = _events(response, lambda ev: sum(k == "comment" for k, _ in ev) >= 5)
    assert not [e for e in events if e[0] == "invalidate"]


def test_sign_out_ends_the_stream(client, app, db):
    sam = _token(db, "sam@example.test")
    headers = {"Authorization": f"Bearer {sam.access_token}"}
    if True:
        def sign_out():
            time.sleep(0.3)
            client.post("/auth/logout", json={"scope": "global"},
                        headers={**headers, "Origin": "https://selkoapp.test"})

        with client.stream("GET", "/live", headers=headers) as response:
            threading.Thread(target=sign_out, daemon=True).start()
            events = _events(response, lambda ev: ev[-1][0] == "revoked")
    assert events[-1][0] == "revoked"


def test_the_stream_ends_when_the_token_expires(client, app, db):
    sam = _token(db, "sam@example.test")
    claims = jwt.decode(sam.access_token, options={"verify_signature": False})
    short = jwt.encode({**claims, "exp": int(time.time()) + 1}, KEYS.current, algorithm="HS256", headers={"kid": "1"})
    with client.stream(
        "GET", "/live", headers={"Authorization": f"Bearer {short}"}
    ) as response:
        events = _events(response, lambda ev: ev[-1][0] == "reauth")
    assert events[-1][0] == "reauth"


def test_no_token_no_stream(client, app):
    assert client.get("/live").status_code == 401


def test_a_user_gets_at_most_five_streams(client, app, db, monkeypatch):
    sam = _token(db, "sam@example.test")
    monkeypatch.setitem(live._open, sam.user["id"], live.MAX_STREAMS_PER_USER)
    response = client.get("/live", headers={"Authorization": f"Bearer {sam.access_token}"})
    assert response.status_code == 429
