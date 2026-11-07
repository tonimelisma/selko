"""The MCP endpoint against real Supabase: a real OAuth grant, real RLS, real RPCs.

Nothing here is mocked. A throwaway OAuth client and user go through Supabase's
OAuth 2.1 server (authorize → consent → token with PKCE), and the token that
comes out is the one Claude would hold. It is then used over streamable HTTP
against the mounted endpoint, so the verifier, the user-scoped PostgREST
client and the review RPCs all run as they do in production.

Requires ``[auth.oauth_server] enabled = true`` in supabase/config.toml. If the
local stack predates that setting, restart it (``supabase stop && supabase
start``) — the first test fails loudly rather than skipping.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import secrets
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from selko.api.mcp import mount_mcp

pytestmark = [pytest.mark.integration, pytest.mark.development]

REDIRECT_URI = "http://localhost:8765/callback"
API = "http://localhost:8000"


def _admin_headers(config) -> dict[str, str]:
    key = config.supabase_service_role_key
    return {"apikey": key, "Authorization": f"Bearer {key}"}


@pytest.fixture
def oauth_client(config):
    """A client that registers itself, as Claude does when a connector is added.

    Uses the dynamic client registration endpoint the authorization server
    advertises, then removes the client with the admin API.
    """
    with httpx.Client(timeout=15) as http:
        metadata = http.get(f"{config.supabase_url}/auth/v1/.well-known/oauth-authorization-server")
        registration = metadata.json().get("registration_endpoint")
        assert registration, (
            "Supabase does not advertise dynamic client registration; restart supabase so "
            "config.toml [auth.oauth_server] allow_dynamic_registration = true applies."
        )
        response = http.post(registration, json={
            "client_name": "Claude (integration test)",
            "redirect_uris": [REDIRECT_URI],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        })
        assert response.status_code == 201, response.text
        client_id = response.json()["client_id"]
        try:
            yield client_id
        finally:
            gone = http.delete(
                f"{config.supabase_url}/auth/v1/admin/oauth/clients/{client_id}",
                headers=_admin_headers(config),
            )
            assert gone.status_code in (200, 204), gone.text


def _session_token(config, email: str, password: str) -> str:
    response = httpx.post(
        f"{config.supabase_url}/auth/v1/token?grant_type=password",
        headers={"apikey": config.supabase_key},
        json={"email": email, "password": password},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _oauth_token(config, client_id: str, session: str) -> str:
    """Authorization code + PKCE, approving on the consent endpoint the web page calls."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    auth = config.supabase_url + "/auth/v1"
    with httpx.Client(timeout=15) as http:
        authorize = http.get(
            f"{auth}/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "s",
                "scope": "openid email",
                "resource": f"{API}/mcp",
            },
        )
        assert authorize.status_code == 302, authorize.text
        consent_page = urlparse(authorize.headers["location"])
        assert consent_page.path == "/oauth/consent"
        authorization_id = parse_qs(consent_page.query)["authorization_id"][0]

        as_user = {"apikey": config.supabase_key, "Authorization": f"Bearer {session}"}
        details = http.get(f"{auth}/oauth/authorizations/{authorization_id}", headers=as_user)
        assert details.status_code == 200 and details.json()["client"]["id"] == client_id
        consent = http.post(
            f"{auth}/oauth/authorizations/{authorization_id}/consent",
            headers=as_user,
            json={"action": "approve"},
        )
        assert consent.status_code == 200, consent.text
        code = parse_qs(urlparse(consent.json()["redirect_url"]).query)["code"][0]

        token = http.post(
            f"{auth}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        assert token.status_code == 200, token.text
        return token.json()["access_token"]


@asynccontextmanager
async def _mcp(config, token: str):
    app = FastAPI()
    server = mount_mcp(app, config)
    async with server.session_manager.run():
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url=API,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        ) as http:
            yield http


@asynccontextmanager
async def _client(http):
    async with Client(streamable_http_client(f"{API}/mcp", http_client=http)) as client:
        yield client


async def _initialize_status(http) -> int:
    response = await http.post(
        "/mcp",
        json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "0"}},
        },
        headers={"Accept": "application/json, text/event-stream"},
    )
    return response.status_code


def _seed(admin_client, user_id: str) -> dict[str, str]:
    """Two New-lane events and one event with a pending change, all in the future."""
    email_id = admin_client.table("emails").insert({
        "user_id": user_id,
        "email_provider": "gmail",
        "provider_message_id": f"mcp-{uuid4()}",
        "subject": "Spring concert",
        "from_email": "office@school.test",
        "from_name": "School Office",
    }).execute().data[0]["id"]

    def event(title: str, review_status: str, start: str, location: str | None = None) -> str:
        return admin_client.table("events").insert({
            "user_id": user_id,
            "title": title,
            "start_datetime": start,
            "end_datetime": start.replace("T18", "T19"),
            "location": location,
            "review_status": review_status,
        }).execute().data[0]["id"]

    concert = event("Spring concert", "pending_review", "2099-04-10T18:00:00Z")
    bake_sale = event("Bake sale", "pending_review", "2099-04-11T18:00:00Z")
    practice = event("Soccer practice", "active", "2099-04-12T18:00:00Z", "South field")
    for event_id, source_type in ((concert, "new_invitation"), (bake_sale, "new_invitation")):
        admin_client.table("event_sources").insert({
            "event_id": event_id, "email_id": email_id, "source_type": source_type,
            "extracted_data": {},
        }).execute()
    source_id = admin_client.table("event_sources").insert({
        "event_id": practice, "email_id": email_id, "source_type": "update",
        "extracted_data": {"location": "North field"},
    }).execute().data[0]["id"]
    admin_client.table("event_change_proposals").insert({
        "event_id": practice,
        "user_id": user_id,
        "source_id": source_id,
        "kind": "material_update",
        "status": "pending",
        "change_set": {"kind": "material_update", "changes": [
            {"field": "location", "before": "South field", "after": "North field"}]},
        "event_snapshot_before": {
            "title": "Soccer practice", "start_datetime": "2099-04-12T18:00:00Z",
            "end_datetime": "2099-04-12T19:00:00Z", "all_day": False, "location": "South field",
            "description": None, "importance": "action_required", "review_status": "active",
        },
    }).execute()
    return {"concert": concert, "bake_sale": bake_sale, "practice": practice}


@pytest.mark.asyncio
async def test_claude_shaped_token_reviews_the_queue_end_to_end(
    config, admin_client, temp_user, oauth_client
):
    user_id, email, password = temp_user
    ids = _seed(admin_client, user_id)
    mcp_config = dataclasses.replace(config, api_public_url=API)
    token = _oauth_token(config, oauth_client, _session_token(config, email, password))

    async with _mcp(mcp_config, token) as http, _client(http) as client:
        queue = (await client.call_tool("list_review_queue", {})).structured_content
        lanes = {item["event_id"]: item["lane"] for item in queue["items"]}
        assert lanes == {ids["concert"]: "new", ids["bake_sale"]: "new", ids["practice"]: "change"}
        assert (queue["new_count"], queue["change_count"]) == (2, 1)
        practice = next(i for i in queue["items"] if i["event_id"] == ids["practice"])
        assert practice["change"]["changes"] == [
            {"field": "location", "before": "South field", "after": "North field"}]
        concert = next(i for i in queue["items"] if i["event_id"] == ids["concert"])
        assert concert["source"]["from"] == "School Office"

        accepted = await client.call_tool("accept_event", {"event_id": ids["concert"]})
        assert not accepted.is_error, accepted.content
        rejected = await client.call_tool("reject_event", {"event_id": ids["bake_sale"]})
        assert not rejected.is_error, rejected.content
        again = await client.call_tool("accept_event", {"event_id": ids["bake_sale"]})
        assert again.is_error and "not waiting for review" in again.content[0].text

        kept = await client.call_tool("reject_change", {"event_id": ids["practice"]})
        assert not kept.is_error, kept.content

        detail = (await client.call_tool("get_event", {"event_id": ids["concert"]})).structured_content
        assert detail["review_status"] == "active"
        assert detail["sources"][0]["subject"] == "Spring concert"

        status = (await client.call_tool("get_account_status", {})).structured_content
        assert status["waiting_for_review"] == {"new": 0, "changes": 0}
        no_mailbox = await client.call_tool("check_email_now", {})
        assert no_mailbox.is_error and "No connected mailbox" in no_mailbox.content[0].text

    events = {
        row["id"]: row["review_status"]
        for row in admin_client.table("events").select("id, review_status")
        .in_("id", list(ids.values())).execute().data
    }
    assert events == {ids["concert"]: "active", ids["bake_sale"]: "rejected", ids["practice"]: "active"}
    work = admin_client.table("calendar_work_items").select("action").eq(
        "event_id", ids["concert"]).execute().data
    assert [item["action"] for item in work] == ["upsert"]
    proposal = admin_client.table("event_change_proposals").select("status").eq(
        "event_id", ids["practice"]).execute().data
    assert [p["status"] for p in proposal] == ["rejected"]
    location = admin_client.table("events").select("location").eq("id", ids["practice"]).execute().data
    assert location[0]["location"] == "South field"  # the rejected change never reached it


@pytest.mark.asyncio
async def test_row_level_security_hides_other_users_events(
    config, admin_client, temp_user, oauth_client
):
    user_id, email, password = temp_user
    stranger = admin_client.auth.admin.create_user({
        "email": f"mcp-stranger-{uuid4()}@selko.local", "password": "testpass123",
        "email_confirm": True,
    }).user
    try:
        theirs = _seed(admin_client, stranger.id)
        mcp_config = dataclasses.replace(config, api_public_url=API)
        token = _oauth_token(config, oauth_client, _session_token(config, email, password))
        async with _mcp(mcp_config, token) as http, _client(http) as client:
            queue = (await client.call_tool("list_review_queue", {})).structured_content
            assert queue["items"] == []
            peek = await client.call_tool("get_event", {"event_id": theirs["concert"]})
            assert peek.is_error and "No event" in peek.content[0].text
            touch = await client.call_tool("accept_event", {"event_id": theirs["concert"]})
            assert touch.is_error
        untouched = admin_client.table("events").select("review_status").eq(
            "id", theirs["concert"]).execute().data
        assert untouched[0]["review_status"] == "pending_review"
    finally:
        admin_client.auth.admin.delete_user(stranger.id)
    assert admin_client.table("events").select("id").eq("user_id", stranger.id).execute().data == []


@pytest.mark.asyncio
async def test_only_tokens_from_the_consent_flow_get_in(config, temp_user, oauth_client):
    _, email, password = temp_user
    session = _session_token(config, email, password)
    token = _oauth_token(config, oauth_client, session)

    mcp_config = dataclasses.replace(config, api_public_url=API)
    async with _mcp(mcp_config, token) as http:
        assert await _initialize_status(http) == 200
    # A web-app session token is a valid Supabase token, but the user never
    # approved an app with it.
    async with _mcp(mcp_config, session) as http:
        assert await _initialize_status(http) == 401
    async with _mcp(mcp_config, "not-a-token") as http:
        assert await _initialize_status(http) == 401


@pytest.mark.asyncio
async def test_disconnecting_the_app_revokes_its_token(config, temp_user, oauth_client):
    """Settings → Connected apps → Disconnect calls this same endpoint."""
    _, email, password = temp_user
    session = _session_token(config, email, password)
    token = _oauth_token(config, oauth_client, session)
    mcp_config = dataclasses.replace(config, api_public_url=API)

    async with _mcp(mcp_config, token) as http:
        assert await _initialize_status(http) == 200
    revoked = httpx.delete(
        f"{config.supabase_url}/auth/v1/user/oauth/grants",
        params={"client_id": oauth_client},
        headers={"apikey": config.supabase_key, "Authorization": f"Bearer {session}"},
        timeout=15,
    )
    assert revoked.status_code in (200, 204), revoked.text
    # A fresh mount has a fresh verifier cache, as a minute later in production.
    async with _mcp(mcp_config, token) as http:
        assert await _initialize_status(http) == 401


@pytest.mark.asyncio
async def test_accepting_a_change_rewrites_the_event_and_queues_the_calendar(
    config, admin_client, temp_user, oauth_client
):
    user_id, email, password = temp_user
    ids = _seed(admin_client, user_id)
    mcp_config = dataclasses.replace(config, api_public_url=API)
    token = _oauth_token(config, oauth_client, _session_token(config, email, password))
    async with _mcp(mcp_config, token) as http, _client(http) as client:
        result = await client.call_tool("accept_change", {"event_id": ids["practice"]})
        assert not result.is_error, result.content
        assert result.structured_content["result"] == "accepted"
        none_left = await client.call_tool("accept_change", {"event_id": ids["practice"]})
        assert none_left.is_error and "no pending change" in none_left.content[0].text
    row = admin_client.table("events").select("location, review_status").eq(
        "id", ids["practice"]).execute().data[0]
    assert row == {"location": "North field", "review_status": "active"}
    work = admin_client.table("calendar_work_items").select("action").eq(
        "event_id", ids["practice"]).execute().data
    assert [item["action"] for item in work] == ["upsert"]
