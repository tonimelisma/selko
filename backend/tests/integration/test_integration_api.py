"""Integration tests for FastAPI endpoints.

Tests API endpoints with real Supabase and JWT authentication.

Note: Tests for data query endpoints (emails, integrations, attachments, etc.)
have been removed as these are now accessed directly via Supabase from frontends.
Only server-side endpoints (OAuth, sync, process) are tested here.
"""

import pytest
from fastapi.testclient import TestClient

from selko.api.app import app


@pytest.fixture
def test_client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def auth_headers(authenticated_client):
    """Get Authorization header with valid JWT token.

    Uses the authenticated Supabase client to get the access token.
    """
    session = authenticated_client.auth.get_session()
    if not session or not session.access_token:
        pytest.skip("No authenticated session available")

    return {"Authorization": f"Bearer {session.access_token}"}


@pytest.mark.integration
@pytest.mark.development
class TestHealthEndpoints:
    """Test health check endpoints (no auth required)."""

    def test_health_check(self, test_client):
        """GET /health returns ok status."""
        response = test_client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_health_db_check(self, test_client):
        """GET /health/db returns connected status."""
        response = test_client.get("/health/db")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["database"] == "connected"


@pytest.mark.integration
@pytest.mark.development
class TestAuthenticationRequired:
    """Test that authenticated endpoints require valid JWT."""

    def test_emails_sync_no_auth(self, test_client):
        """POST /emails/sync without auth returns 401."""
        response = test_client.post("/emails/sync", json={"max_results": 10})

        assert response.status_code == 401
        assert "Missing Authorization header" in response.json()["detail"]

    def test_emails_sync_invalid_auth(self, test_client):
        """POST /emails/sync with invalid token returns 401."""
        response = test_client.post(
            "/emails/sync",
            json={"max_results": 10},
            headers={"Authorization": "Bearer invalid_token"}
        )

        assert response.status_code == 401
        assert "Invalid or expired token" in response.json()["detail"]

    def test_emails_sync_malformed_auth(self, test_client):
        """POST /emails/sync with malformed header returns 401."""
        response = test_client.post(
            "/emails/sync",
            json={"max_results": 10},
            headers={"Authorization": "NotBearer"}
        )

        assert response.status_code == 401
        assert "Invalid Authorization header format" in response.json()["detail"]

    def test_calendars_no_auth(self, test_client):
        """GET /calendars without auth returns 401."""
        response = test_client.get("/calendars")

        assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.development
class TestEmailSyncEndpoints:
    """Test email sync and process endpoints (server-side operations)."""

    def test_email_sync_no_integration(self, test_client, temp_user_client):
        """POST /emails/sync returns error when no Gmail integration."""
        # Use temp_user who doesn't have any integration configured
        session = temp_user_client.auth.get_session()
        headers = {"Authorization": f"Bearer {session.access_token}"}

        response = test_client.post(
            "/emails/sync",
            json={"max_results": 10, "fetch_attachments": True},
            headers=headers,
        )

        # Should return error if no Gmail integration configured
        assert response.status_code in [404, 500]

    def test_email_sync_validation(self, test_client, auth_headers):
        """POST /emails/sync validates request parameters."""
        # Test invalid max_results (out of range)
        response = test_client.post(
            "/emails/sync",
            json={"max_results": 0, "fetch_attachments": True},
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error

    def test_email_process_not_found(self, test_client, auth_headers):
        """POST /emails/{id}/process returns 404 for non-existent email."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = test_client.post(f"/emails/{fake_id}/process", headers=auth_headers)

        assert response.status_code == 404

    def test_batch_process_validation(self, test_client, auth_headers):
        """POST /emails/batch-process validates request parameters."""
        # Test invalid max_emails (out of range)
        response = test_client.post(
            "/emails/batch-process",
            json={"max_emails": 0},
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error


@pytest.mark.integration
@pytest.mark.development
class TestOAuthEndpoints:
    """Test OAuth integration endpoints."""

    def test_gmail_auth_requires_authentication(self, test_client):
        """GET /integrations/gmail/auth requires authentication."""
        response = test_client.get("/integrations/gmail/auth")

        assert response.status_code == 401

    def test_gmail_auth_redirect(self, test_client, auth_headers):
        """GET /integrations/gmail/auth returns redirect."""
        response = test_client.get(
            "/integrations/gmail/auth", headers=auth_headers, follow_redirects=False
        )

        # Should redirect to Google OAuth or return error if credentials missing
        assert response.status_code in [302, 500]


@pytest.mark.integration
@pytest.mark.development
class TestOAuthCallback:
    """Test OAuth callback endpoint (public, state-protected)."""

    def test_callback_no_auth_required(self, test_client):
        """Callback does not require JWT (security fix verification)."""
        response = test_client.get(
            "/integrations/gmail/callback?code=test&state=invalid"
        )
        # Should return 400 (invalid state), NOT 401 (missing auth)
        assert response.status_code != 401
        assert response.status_code == 400

    def test_callback_invalid_state(self, test_client):
        """Callback rejects invalid state."""
        response = test_client.get(
            "/integrations/gmail/callback?code=test&state=invalid123"
        )
        assert response.status_code == 400
        # Error message is sanitized to not leak internal details
        assert "invalid" in response.json()["detail"].lower() or "expired" in response.json()["detail"].lower()

    def test_callback_expired_state(self, test_client):
        """Callback rejects expired state (>10 min)."""
        from datetime import datetime, timedelta
        from selko.services.integrations import _oauth_states
        import secrets

        state = secrets.token_urlsafe(32)
        _oauth_states[state] = {
            "user_id": "test-user",
            "provider": "gmail",
            "created_at": datetime.utcnow() - timedelta(minutes=11),
            "redirect_uri": "http://localhost:8000/integrations/gmail/callback",
        }

        try:
            response = test_client.get(
                f"/integrations/gmail/callback?code=test&state={state}"
            )
            assert response.status_code == 400
            assert "expired" in response.json()["detail"].lower()
        finally:
            _oauth_states.pop(state, None)

    def test_callback_success_mocked(self, test_client, config, temp_user):
        """Callback successfully saves credentials (mocked token exchange)."""
        from datetime import datetime
        from unittest.mock import Mock, patch
        from selko.services.integrations import _oauth_states
        import secrets

        user_id, email, password = temp_user

        # Create valid state
        state = secrets.token_urlsafe(32)
        _oauth_states[state] = {
            "user_id": user_id,
            "provider": "gmail",
            "created_at": datetime.utcnow(),
            "redirect_uri": "http://localhost:8000/integrations/gmail/callback",
        }

        # Mock token exchange
        mock_creds = Mock()
        mock_creds.token = "test_token"
        mock_creds.refresh_token = "test_refresh"
        mock_creds.scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
        mock_creds.expiry = None

        with patch(
            "selko.api.routes.integrations.complete_oauth_flow",
            return_value=(mock_creds, user_id, "gmail"),
        ), patch(
            "selko.api.routes.integrations.build_service",
            return_value=Mock(),
        ), patch(
            "selko.api.routes.integrations.get_user_profile",
            return_value={"emailAddress": "test@gmail.com"},
        ):
            try:
                response = test_client.get(
                    f"/integrations/gmail/callback?code=test_code&state={state}"
                )

                assert response.status_code == 200
                assert response.json()["status"] == "success"

                # Verify credentials saved with correct user_id
                from selko.services.auth import get_service_client
                service_client = get_service_client(config)
                result = (
                    service_client.table("integrations")
                    .select("*")
                    .eq("user_id", user_id)
                    .eq("provider", "gmail")
                    .maybe_single()
                    .execute()
                )
                assert result.data is not None
                assert result.data["provider_email"] == "test@gmail.com"

            finally:
                _oauth_states.pop(state, None)
                from selko.services.auth import get_service_client
                service_client = get_service_client(config)
                service_client.table("integrations").delete().eq(
                    "user_id", user_id
                ).eq("provider", "gmail").execute()


@pytest.mark.integration
@pytest.mark.development
class TestEventSyncEndpoint:
    """Test event sync endpoint (server-side Calendar API)."""

    def test_event_sync_not_found(self, test_client, auth_headers):
        """POST /events/{id}/sync returns 404 for non-existent event."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = test_client.post(f"/events/{fake_id}/sync", headers=auth_headers)

        assert response.status_code == 404

    def test_event_sync_requires_authentication(self, test_client):
        """POST /events/{id}/sync requires authentication."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = test_client.post(f"/events/{fake_id}/sync")

        assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.development
class TestCORSConfiguration:
    """Test CORS middleware configuration."""

    def test_cors_headers_on_allowed_origin(self, test_client):
        """Response includes CORS headers for allowed origin."""
        response = test_client.get(
            "/health",
            headers={"Origin": "http://localhost:3000"}
        )

        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
        assert response.headers.get("access-control-allow-credentials") == "true"

    def test_cors_headers_vite_origin(self, test_client):
        """Response includes CORS headers for Vite dev server origin."""
        response = test_client.get(
            "/health",
            headers={"Origin": "http://localhost:5173"}
        )

        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_cors_headers_127_origin(self, test_client):
        """Response includes CORS headers for 127.0.0.1 origin."""
        response = test_client.get(
            "/health",
            headers={"Origin": "http://127.0.0.1:3000"}
        )

        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:3000"

    def test_cors_preflight_request(self, test_client):
        """OPTIONS preflight request returns proper CORS headers."""
        response = test_client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            }
        )

        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
        assert "GET" in response.headers.get("access-control-allow-methods", "")
        assert response.headers.get("access-control-allow-credentials") == "true"

    def test_cors_preflight_with_custom_headers(self, test_client):
        """OPTIONS preflight allows Authorization header."""
        response = test_client.options(
            "/emails/sync",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            }
        )

        assert response.status_code == 200
        # Should allow all headers (allow_headers=["*"])
        assert response.headers.get("access-control-allow-headers") is not None

    def test_cors_on_authenticated_endpoint(self, test_client, auth_headers):
        """CORS headers present on authenticated endpoints."""
        headers = {**auth_headers, "Origin": "http://localhost:3000"}
        response = test_client.post(
            "/emails/sync",
            json={"max_results": 10},
            headers=headers
        )

        # Response may fail (no Gmail integration) but CORS headers should be present
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
        assert response.headers.get("access-control-allow-credentials") == "true"

    def test_cors_on_post_request(self, test_client, auth_headers):
        """CORS headers present on POST requests."""
        headers = {**auth_headers, "Origin": "http://localhost:5173"}
        # Use an endpoint that accepts POST
        response = test_client.post(
            "/emails/sync",
            headers=headers,
            json={"max_results": 1}
        )

        # Response may fail (no Gmail integration) but CORS headers should be present
        assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_cors_not_allowed_origin(self, test_client):
        """Response does not include CORS headers for disallowed origin."""
        response = test_client.get(
            "/health",
            headers={"Origin": "https://evil-site.com"}
        )

        assert response.status_code == 200
        # When origin is not allowed, the header should not be present
        # or should not match the requested origin
        cors_origin = response.headers.get("access-control-allow-origin")
        assert cors_origin != "https://evil-site.com"

    def test_cors_no_origin_header(self, test_client):
        """Request without Origin header still works (same-origin request)."""
        response = test_client.get("/health")

        assert response.status_code == 200
        # No CORS headers needed for same-origin requests
        data = response.json()
        assert data["status"] == "ok"

    def test_cors_preflight_disallowed_origin(self, test_client):
        """OPTIONS preflight from disallowed origin is handled."""
        response = test_client.options(
            "/health",
            headers={
                "Origin": "https://evil-site.com",
                "Access-Control-Request-Method": "GET",
            }
        )

        # Request goes through but CORS headers won't allow the origin
        cors_origin = response.headers.get("access-control-allow-origin")
        assert cors_origin != "https://evil-site.com"
