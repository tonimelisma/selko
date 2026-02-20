"""Unit tests for API routes.

Tests FastAPI route handlers with mocked dependencies. No real Supabase or
external services needed — all deps are overridden via app.dependency_overrides.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from selko.api.app import create_app
from selko.api.deps import (
    CurrentUser,
    get_authenticated_client,
    get_config,
    get_current_user,
    get_llm_gateway,
    get_quota_service,
    get_service_role_client,
)
from selko.config import Config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config():
    """Config with test values."""
    return Config(
        environment="development",
        supabase_url="http://localhost:54321",
        supabase_key="test-anon-key",
        supabase_service_role_key="test-service-key",
        google_client_id="test-client-id",
        google_client_secret="test-client-secret",
        test_user_email="test@example.com",
        test_user_password="testpass",
    )


@pytest.fixture
def mock_user():
    """Authenticated user for dependency overrides."""
    return CurrentUser(id="test-user-id", email="test@example.com", token="fake-jwt")


@pytest.fixture
def mock_client():
    """Mock Supabase client."""
    return MagicMock()


@pytest.fixture
def mock_quota():
    """Mock QuotaService that always allows."""
    qs = MagicMock()
    qs.check_and_increment.return_value = MagicMock(
        allowed=True, remaining=9, limit=10, resets_at="2026-01-02T00:00:00Z"
    )
    return qs


@pytest.fixture
def mock_gateway():
    """Mock LLMGateway."""
    return MagicMock()


@pytest.fixture
def test_client(mock_config, mock_user, mock_client, mock_quota, mock_gateway):
    """Fully-overridden TestClient — all deps mocked."""
    app = create_app()
    app.dependency_overrides[get_config] = lambda: mock_config
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_authenticated_client] = lambda: mock_client
    app.dependency_overrides[get_quota_service] = lambda: mock_quota
    app.dependency_overrides[get_service_role_client] = lambda: mock_client
    app.dependency_overrides[get_llm_gateway] = lambda: mock_gateway
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture
def unauthed_app(mock_config):
    """App with only config overridden — auth will fail against fake Supabase."""
    app = create_app()
    app.dependency_overrides[get_config] = lambda: mock_config
    yield app
    app.dependency_overrides.clear()


# ===========================================================================
# Health endpoints
# ===========================================================================


class TestHealthEndpoints:
    """Tests for /health and /health/db."""

    def test_health_ok(self, test_client):
        resp = test_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_health_db_connected(self, test_client, mock_config):
        """Mock create_client so health/db succeeds."""
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.limit.return_value.execute.return_value = (
            MagicMock(data=[{"id": "x"}])
        )
        with patch("selko.api.routes.health.create_client", return_value=mock_sb):
            resp = test_client.get("/health/db")
        assert resp.status_code == 200
        assert resp.json()["database"] == "connected"

    def test_health_db_failure(self, test_client, mock_config):
        """Database connectivity failure returns 503."""
        with patch(
            "selko.api.routes.health.create_client",
            side_effect=Exception("connection refused"),
        ):
            resp = test_client.get("/health/db")
        assert resp.status_code == 503


# ===========================================================================
# Auth validation
# ===========================================================================


class TestAuthValidation:
    """Tests for authentication enforcement on protected endpoints."""

    def test_no_auth_header_returns_401(self, unauthed_app):
        """Missing Authorization header -> 401."""
        client = TestClient(unauthed_app, raise_server_exceptions=False)
        resp = client.post("/emails/sync", json={})
        assert resp.status_code == 401

    def test_malformed_bearer_returns_401(self, unauthed_app):
        """Bearer prefix missing -> 401."""
        client = TestClient(unauthed_app, raise_server_exceptions=False)
        resp = client.post(
            "/emails/sync",
            json={},
            headers={"Authorization": "Token abc123"},
        )
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, unauthed_app):
        """Valid Bearer format but fake token -> 401 from Supabase validation."""
        client = TestClient(unauthed_app, raise_server_exceptions=False)
        resp = client.post(
            "/emails/sync",
            json={},
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401

    def test_events_sync_requires_auth(self, unauthed_app):
        """Events sync endpoint also requires auth."""
        client = TestClient(unauthed_app, raise_server_exceptions=False)
        resp = client.post("/events/00000000-0000-0000-0000-000000000001/sync")
        assert resp.status_code == 401

    def test_integrations_gmail_auth_requires_auth(self, unauthed_app):
        """Gmail OAuth initiation requires auth."""
        client = TestClient(unauthed_app, raise_server_exceptions=False)
        resp = client.get("/integrations/gmail/auth")
        assert resp.status_code == 401


# ===========================================================================
# CORS headers
# ===========================================================================


class TestCORSHeaders:
    """Tests for CORS middleware configuration."""

    def test_allowed_origin(self, test_client):
        resp = test_client.get(
            "/health",
            headers={"Origin": "http://localhost:5173"},
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_disallowed_origin(self, test_client):
        resp = test_client.get(
            "/health",
            headers={"Origin": "http://evil.example.com"},
        )
        assert "access-control-allow-origin" not in resp.headers

    def test_preflight(self, test_client):
        resp = test_client.options(
            "/emails/sync",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_no_origin_no_cors_header(self, test_client):
        resp = test_client.get("/health")
        assert "access-control-allow-origin" not in resp.headers


# ===========================================================================
# Request validation (422)
# ===========================================================================


class TestRequestValidation:
    """Tests for Pydantic request validation returning 422."""

    def test_sync_invalid_max_results(self, test_client):
        resp = test_client.post("/emails/sync", json={"max_results": 0})
        assert resp.status_code == 422

    def test_batch_process_invalid_max_emails(self, test_client):
        resp = test_client.post("/emails/batch-process", json={"max_emails": 999})
        assert resp.status_code == 422


# ===========================================================================
# Not-found responses
# ===========================================================================


class TestNotFoundResponses:
    """Tests for 404 when resources don't exist."""

    def test_email_not_found(self, test_client, mock_client):
        """Processing a non-existent email returns 404."""
        mock_result = MagicMock()
        mock_result.data = None
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = mock_result

        resp = test_client.post("/emails/some-fake-id/process")
        assert resp.status_code == 404

    def test_event_sync_not_found(self, test_client, mock_client):
        """Syncing a non-existent event returns 404."""
        mock_result = MagicMock()
        mock_result.data = None
        mock_client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = mock_result

        resp = test_client.post("/events/00000000-0000-0000-0000-000000000001/sync")
        assert resp.status_code == 404

    def test_event_unsync_not_found(self, test_client, mock_client):
        """Unsyncing a non-existent event returns 404."""
        mock_result = MagicMock()
        mock_result.data = None
        mock_client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = mock_result

        resp = test_client.post("/events/00000000-0000-0000-0000-000000000001/unsync")
        assert resp.status_code == 404


# ===========================================================================
# OAuth callback (public endpoint)
# ===========================================================================


class TestOAuthCallback:
    """Tests for the Google OAuth callback endpoint."""

    def test_callback_invalid_state(self, test_client):
        """Invalid state returns 400."""
        from selko.services.integrations import OAuthStateError

        with patch(
            "selko.api.routes.integrations.complete_oauth_flow",
            side_effect=OAuthStateError("Invalid or expired state parameter"),
        ):
            resp = test_client.get(
                "/integrations/google/callback",
                params={"code": "auth-code", "state": "bad-state"},
            )
        assert resp.status_code == 400

    def test_callback_expired_state(self, test_client):
        """Expired state returns 400."""
        from selko.services.integrations import OAuthStateError

        with patch(
            "selko.api.routes.integrations.complete_oauth_flow",
            side_effect=OAuthStateError("State parameter expired"),
        ):
            resp = test_client.get(
                "/integrations/google/callback",
                params={"code": "auth-code", "state": "expired-state"},
            )
        assert resp.status_code == 400

    def test_callback_success(self, test_client, mock_config):
        """Successful callback returns 200 with provider info."""
        mock_creds = MagicMock()
        with (
            patch(
                "selko.api.routes.integrations.complete_oauth_flow",
                return_value=(mock_creds, "test-user-id", "gmail"),
            ),
            patch("selko.services.auth.get_service_client"),
            patch("selko.api.routes.integrations.build_service"),
            patch(
                "selko.api.routes.integrations.get_user_profile",
                return_value={"emailAddress": "user@gmail.com"},
            ),
            patch("selko.api.routes.integrations.save_oauth_credentials"),
        ):
            resp = test_client.get(
                "/integrations/google/callback",
                params={"code": "valid-code", "state": "valid-state"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["provider"] == "gmail"
        assert data["provider_email"] == "user@gmail.com"

    def test_callback_no_auth_required(self, test_client):
        """Callback endpoint is public — no JWT needed. Verify it doesn't 401."""
        from selko.services.integrations import IntegrationError

        # Even an IntegrationError proves we reached the handler (no 401 gate)
        with patch(
            "selko.api.routes.integrations.complete_oauth_flow",
            side_effect=IntegrationError("Invalid or expired state"),
        ):
            resp = test_client.get(
                "/integrations/google/callback",
                params={"code": "any-code", "state": "any-state"},
            )
        assert resp.status_code != 401


# ===========================================================================
# Redirect URI validation
# ===========================================================================


class TestRedirectURIValidation:
    """Tests for OAuth redirect URI allowlist."""

    def test_valid_redirect_uri(self, test_client):
        """Valid redirect URI initiates OAuth (mock the flow)."""
        with patch(
            "selko.api.routes.integrations.initiate_oauth_flow",
            return_value={"auth_url": "https://accounts.google.com/o/oauth2"},
        ):
            resp = test_client.get(
                "/integrations/gmail/auth",
                params={
                    "redirect_uri": "http://localhost:8000/integrations/google/callback"
                },
                follow_redirects=False,
            )
        assert resp.status_code == 302

    def test_invalid_redirect_uri_returns_400(self, test_client):
        """Disallowed redirect URI returns 400."""
        resp = test_client.get(
            "/integrations/gmail/auth",
            params={"redirect_uri": "http://evil.example.com/callback"},
            follow_redirects=False,
        )
        assert resp.status_code == 400
