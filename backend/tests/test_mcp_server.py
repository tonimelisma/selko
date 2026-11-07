"""Unit tests for the MCP endpoint: auth, tool contract, widget, HTTP wiring.

The data path (RLS reads, RPC writes) is exercised against a real database in
``tests/integration/test_integration_mcp.py``.
"""

from __future__ import annotations

import dataclasses
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx2
import pytest
from fastapi import FastAPI
from jose import jwt
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import AccessToken

from selko.api.mcp import create_mcp_server, mount_mcp
from selko.api.mcp.auth import SupabaseTokenVerifier
from selko.api.mcp.operations import _change_summary, _when
from selko.api.mcp.server import REVIEW_WIDGET_URI, _widget_html

USER_ID = "11111111-1111-1111-1111-111111111111"
CLIENT_ID = "22222222-2222-2222-2222-222222222222"


def _token(**claims) -> str:
    base = {"sub": USER_ID, "aud": "authenticated", "exp": 4102444800, "client_id": CLIENT_ID}
    base.update(claims)
    return jwt.encode({k: v for k, v in base.items() if v is not None}, "test-secret", algorithm="HS256")


# ------------------------------------------------------------------- verifier


class _Validator:
    def __init__(self, answer: str | None = USER_ID) -> None:
        self.answer = answer
        self.calls = 0

    def __call__(self, token: str) -> str | None:
        self.calls += 1
        return self.answer


@pytest.mark.asyncio
async def test_verifier_accepts_an_allowlisted_oauth_token():
    validator = _Validator()
    verifier = SupabaseTokenVerifier(validator, frozenset({CLIENT_ID}))
    access = await verifier.verify_token(_token(scope="openid email"))
    assert access is not None
    assert access.subject == USER_ID
    assert access.client_id == CLIENT_ID
    assert access.scopes == ["openid", "email"]


@pytest.mark.asyncio
async def test_verifier_rejects_a_browser_session_token_without_asking_supabase():
    """A web-app session token is valid for Supabase but was not minted for MCP."""
    validator = _Validator()
    verifier = SupabaseTokenVerifier(validator, frozenset({CLIENT_ID}))
    assert await verifier.verify_token(_token(client_id=None)) is None
    assert validator.calls == 0


@pytest.mark.asyncio
async def test_verifier_rejects_a_client_that_is_not_allowlisted():
    validator = _Validator()
    verifier = SupabaseTokenVerifier(validator, frozenset({CLIENT_ID}))
    assert await verifier.verify_token(_token(client_id="someone-else")) is None
    assert validator.calls == 0


@pytest.mark.asyncio
async def test_empty_allowlist_accepts_nothing():
    verifier = SupabaseTokenVerifier(_Validator(), frozenset())
    assert await verifier.verify_token(_token()) is None


@pytest.mark.asyncio
async def test_verifier_rejects_what_supabase_rejects():
    verifier = SupabaseTokenVerifier(_Validator(answer=None), frozenset({CLIENT_ID}))
    assert await verifier.verify_token(_token()) is None


@pytest.mark.asyncio
async def test_verifier_rejects_a_token_whose_subject_supabase_disputes():
    verifier = SupabaseTokenVerifier(_Validator(answer="another-user"), frozenset({CLIENT_ID}))
    assert await verifier.verify_token(_token()) is None


@pytest.mark.asyncio
async def test_verifier_rejects_garbage():
    verifier = SupabaseTokenVerifier(_Validator(), frozenset({CLIENT_ID}))
    assert await verifier.verify_token("not-a-jwt") is None


@pytest.mark.asyncio
async def test_validation_is_cached_briefly_then_repeated():
    """A revoked grant must stop working: the cache expires."""
    now = [0.0]
    validator = _Validator()
    verifier = SupabaseTokenVerifier(validator, frozenset({CLIENT_ID}), clock=lambda: now[0])
    token = _token()
    await verifier.verify_token(token)
    await verifier.verify_token(token)
    assert validator.calls == 1
    now[0] = 61.0
    validator.answer = None  # revoked meanwhile
    assert await verifier.verify_token(token) is None
    assert validator.calls == 2


# ------------------------------------------------------------- tool contract


class _AllowAll:
    async def verify_token(self, token: str) -> AccessToken | None:
        return AccessToken(token=token, client_id=CLIENT_ID, scopes=[], subject=USER_ID)


@pytest.fixture
def mcp_config(mock_config):
    return dataclasses.replace(
        mock_config,
        api_public_url="https://api.example.test",
        frontend_url="https://app.example.test",
        mcp_oauth_client_ids=(CLIENT_ID,),
    )


@pytest.mark.asyncio
async def test_every_tool_is_annotated_and_reads_are_split_from_writes(mcp_config):
    server = create_mcp_server(mcp_config, token_verifier=_AllowAll())
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == {
        "list_review_queue", "get_event", "list_calendar_events", "list_recent_activity",
        "get_account_status", "accept_event", "reject_event", "accept_change",
        "reject_change", "check_email_now",
    }
    reads = {"list_review_queue", "get_event", "list_calendar_events",
             "list_recent_activity", "get_account_status"}
    for name, tool in by_name.items():
        assert len(name) <= 64
        assert tool.annotations is not None, name
        assert tool.annotations.title, name
        assert tool.annotations.read_only_hint is (name in reads), name
        assert tool.annotations.destructive_hint is not None, name
        assert tool.description and len(tool.description) > 40, name
    # Destructive: the two decisions that cannot be undone from here.
    destructive = {n for n, t in by_name.items() if t.annotations.destructive_hint}
    assert destructive == {"reject_event", "accept_change"}


@pytest.mark.asyncio
async def test_review_queue_tool_points_at_the_widget(mcp_config):
    server = create_mcp_server(mcp_config, token_verifier=_AllowAll())
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        resource = await client.read_resource(REVIEW_WIDGET_URI)
    meta = tools["list_review_queue"].meta or {}
    assert meta["ui"]["resourceUri"] == REVIEW_WIDGET_URI
    content = resource.contents[0]
    assert content.mime_type == "text/html;profile=mcp-app"
    assert "globalThis.ExtApps={" in content.text


def test_widget_inlines_the_runtime_and_keeps_no_placeholder():
    html = _widget_html()
    assert "/*__EXT_APPS_BUNDLE__*/" not in html
    assert "globalThis.ExtApps={" in html
    assert "App:" in html  # the class the widget destructures
    # The module may not end in an export statement once inlined.
    assert "export{" not in html[-2000:]


@pytest.mark.asyncio
async def test_tools_refuse_to_run_without_a_signed_in_user(mcp_config):
    """In-process calls carry no access token; the tool must not fall through."""
    server = create_mcp_server(mcp_config, token_verifier=_AllowAll())
    async with Client(server) as client:
        result = await client.call_tool("get_account_status", {})
    assert result.is_error
    assert "Not signed in" in result.content[0].text


# --------------------------------------------------------------- HTTP wiring


@asynccontextmanager
async def _http_app(config, verifier):
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    server = create_mcp_server(config, token_verifier=verifier)
    mount_mcp(app, config, server)
    async with server.session_manager.run():
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="https://api.example.test") as http:
            yield http


@pytest.mark.asyncio
async def test_unauthenticated_request_gets_401_pointing_at_resource_metadata(mcp_config):
    async with _http_app(mcp_config, _AllowAll()) as http:
        response = await http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 401
    header = response.headers["www-authenticate"]
    assert header.startswith("Bearer")
    assert (
        'resource_metadata="https://api.example.test/.well-known/oauth-protected-resource/mcp"'
        in header
    )


@pytest.mark.asyncio
async def test_protected_resource_metadata_names_supabase_as_the_authorization_server(mcp_config):
    async with _http_app(mcp_config, _AllowAll()) as http:
        response = await http.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    body = response.json()
    assert body["resource"] == "https://api.example.test/mcp"
    assert body["authorization_servers"] == ["http://localhost:54321/auth/v1"]


@pytest.mark.asyncio
async def test_mount_does_not_shadow_api_routes(mcp_config):
    async with _http_app(mcp_config, _AllowAll()) as http:
        response = await http.get("/health")
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_authenticated_client_can_list_tools_over_http(mcp_config):
    async with _http_app(mcp_config, _AllowAll()) as http:
        http.headers["Authorization"] = "Bearer anything"
        transport = streamable_http_client("https://api.example.test/mcp", http_client=http)
        async with Client(transport) as client:
            names = {t.name for t in (await client.list_tools()).tools}
    assert "list_review_queue" in names


def test_create_app_mounts_the_mcp_endpoint(monkeypatch, mcp_config):
    """The production app factory wires /mcp, not only the test harness."""
    import selko.api.app as app_module

    monkeypatch.setattr(app_module, "load_config", lambda: mcp_config)
    app = app_module.create_app()
    assert getattr(app.state, "mcp_server", None) is not None
    from starlette.routing import Mount

    # The root mount is last, so every API route keeps priority over it.
    assert isinstance(app.routes[-1], Mount) and app.routes[-1].path == ""
    assert not any(isinstance(route, Mount) for route in app.routes[:-1])


# ------------------------------------------------------------- formatting


TZ = ZoneInfo("America/Los_Angeles")


def test_timed_event_is_reported_in_the_users_timezone():
    when = _when(
        {"all_day": False, "start_datetime": "2026-11-10T02:00:00+00:00",
         "end_datetime": "2026-11-10T03:30:00Z"},
        TZ,
    )
    assert when == {"all_day": False, "start": "2026-11-09T18:00-08:00", "end": "2026-11-09T19:30-08:00"}


def test_single_day_all_day_event_has_no_end_date():
    when = _when(
        {"all_day": True, "start_datetime": "2026-11-10T08:00:00Z",
         "end_datetime": "2026-11-11T07:59:59Z"},
        TZ,
    )
    assert when == {"all_day": True, "start_date": "2026-11-10", "end_date": None}


def test_change_summary_localizes_times_and_names_cancellations():
    summary = _change_summary(
        {"id": "p1", "kind": "material_update", "change_set": {"changes": [
            {"field": "start_datetime", "before": "2026-11-10T02:00:00Z", "after": "2026-11-10T03:00:00Z"},
            {"field": "location", "before": "Gym", "after": "Library"},
        ]}},
        TZ,
    )
    assert summary["kind"] == "update"
    assert summary["changes"][0] == {
        "field": "start_datetime", "before": "2026-11-09T18:00-08:00", "after": "2026-11-09T19:00-08:00"
    }
    assert _change_summary({"id": "p2", "kind": "cancellation", "change_set": {}}, TZ)["kind"] == "cancellation"
