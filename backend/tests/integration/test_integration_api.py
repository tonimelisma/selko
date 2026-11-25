"""Integration tests for FastAPI endpoints.

The real app on a real SQLite database, with real Selko access tokens for real
accounts (docs/specs/sqlite-single-process/05-verification.md §A.2 row 2).
Only the providers' token exchange and the LLM are mocked.
"""

import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from selko.api.app import create_app
from selko.api.deps import get_config, get_llm_gateway
from selko.config import Config
from selko.db import health as db_health
from selko.db import runtime
from selko.services import accounts

JWT_SECRET = "integration-api-test-secret-" + "x" * 20


@pytest.fixture
def api_config():
    return Config(
        environment="development",
        google_client_id="test-client-id",
        google_client_secret="test-client-secret",
        jwt_secret=JWT_SECRET,
    )


@pytest.fixture
def test_client(db, api_config):
    """The FastAPI app with the test database as its process database."""
    runtime.use_database(db)
    # The callback's per-IP limiter is process state shared by every test.
    from selko.api.routes import integrations as integration_routes

    integration_routes._callback_request_log.clear()
    app = create_app()
    app.state.db = db
    app.dependency_overrides[get_config] = lambda: api_config
    app.dependency_overrides[get_llm_gateway] = lambda: MagicMock()
    yield TestClient(app)
    app.dependency_overrides.clear()
    runtime.use_database(None)


@pytest.fixture
def api_user(factory):
    return factory.user()


@pytest.fixture
def auth_headers(api_user):
    """A valid Selko access token for a real account."""
    token, _ = accounts.issue_access_token(
        accounts.TokenKeys(JWT_SECRET), api_user, "api-user@example.test", "session-1"
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
class TestHealthEndpoints:
    """Test health check endpoints (no auth required)."""

    def test_health_check(self, test_client, db, factory):
        """GET /health reports exactly what health_work_state reports.

        The contract worth pinning is that the endpoint is driven by the
        roll-up rather than hard-coded, in both directions.
        """
        body = test_client.get("/health").json()
        assert "resolution" in body
        assert body["status"] == db_health.health_work_state(db, 1800)["status"] == "ok"

        factory.email(factory.user(), processing_status="processing")  # a stale lease
        body = test_client.get("/health").json()
        assert body["status"] == db_health.health_work_state(db, 1800)["status"] == "degraded", (
            "/health disagreed with health_work_state; it is not driven by the roll-up"
        )

    def test_health_db_check(self, test_client):
        """GET /health/db returns connected status."""
        response = test_client.get("/health/db")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["database"] == "connected"

    def test_health_ingestion_and_egress_keep_the_asserted_keys(self, test_client):
        """Every key scripts/assert-health.sh reads is still published."""
        ingestion = test_client.get("/health/ingestion").json()
        for key in ("status", "background_processing_enabled", "tasks", "items_stalled_seconds",
                    "items_dead_letter", "attachments_dead_letter", "stale_processing_emails",
                    "unclaimable_pending", "listener"):
            assert key in ingestion, key
        assert ingestion["listener"]["kind"] == "in_process"
        assert test_client.get("/health/egress").json()["transport"] == "sqlite"


@pytest.mark.integration
class TestAuthenticationRequired:
    """Test that authenticated endpoints require a valid Selko token."""

    def test_emails_sync_no_auth(self, test_client):
        """POST /emails/sync without auth returns 401."""
        response = test_client.post("/emails/sync", json={"max_results": 10})

        assert response.status_code == 401
        detail = response.json()["detail"]
        msg = detail["detail"] if isinstance(detail, dict) else detail
        assert "Missing Authorization header" in msg

    def test_emails_sync_invalid_auth(self, test_client):
        """POST /emails/sync with invalid token returns 401."""
        response = test_client.post(
            "/emails/sync",
            json={"max_results": 10},
            headers={"Authorization": "Bearer invalid_token"}
        )

        assert response.status_code == 401
        detail = response.json()["detail"]
        msg = detail["detail"] if isinstance(detail, dict) else detail
        assert "Invalid or expired token" in msg

    def test_emails_sync_malformed_auth(self, test_client):
        """POST /emails/sync with malformed header returns 401."""
        response = test_client.post(
            "/emails/sync",
            json={"max_results": 10},
            headers={"Authorization": "NotBearer"}
        )

        assert response.status_code == 401
        detail = response.json()["detail"]
        msg = detail["detail"] if isinstance(detail, dict) else detail
        assert "Invalid Authorization header format" in msg

    def test_calendars_no_auth(self, test_client):
        """GET /calendars without auth returns 401."""
        response = test_client.get("/calendars")

        assert response.status_code == 401


@pytest.mark.integration
class TestEmailSyncEndpoints:
    """Test email sync and process endpoints (server-side operations)."""

    def test_email_sync_no_integration(self, test_client, auth_headers):
        """POST /emails/sync returns error when no Gmail integration."""
        response = test_client.post(
            "/emails/sync",
            json={"max_results": 10, "fetch_attachments": True},
            headers=auth_headers,
        )

        assert response.status_code in [404, 500]

    def test_email_sync_validation(self, test_client, auth_headers):
        """POST /emails/sync validates request parameters."""
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
        response = test_client.post(
            "/emails/batch-process",
            json={"max_emails": 0},
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error


@pytest.mark.integration
class TestOAuthEndpoints:
    """Test OAuth integration endpoints."""

    def test_google_auth_requires_authentication(self, test_client):
        response = test_client.get("/integrations/google/auth")

        assert response.status_code == 401

    def test_google_auth_redirect_stores_its_state(self, test_client, auth_headers, db, api_user):
        """GET /integrations/google/auth redirects to Google and records a one-time state."""
        response = test_client.get(
            "/integrations/google/auth", headers=auth_headers, follow_redirects=False
        )

        assert response.status_code == 302
        assert response.headers["location"].startswith("https://accounts.google.com/")
        state = db.query_one("SELECT * FROM oauth_states WHERE user_id = ?", (api_user,))
        assert state["provider"] == "google"
        assert state["code_verifier"], "PKCE verifier kept for the exchange"

    @pytest.mark.parametrize(
        "path", ["/integrations/gmail/auth", "/integrations/calendar/auth"]
    )
    def test_old_mobile_only_paths_are_gone(self, test_client, auth_headers, path):
        """Removed with the native apps (legacy/); the web uses /google/auth."""
        response = test_client.get(path, headers=auth_headers, follow_redirects=False)

        assert response.status_code == 404


@pytest.mark.integration
class TestOAuthCallback:
    """Test OAuth callback endpoint (public, state-protected)."""

    def test_callback_no_auth_required(self, test_client):
        """Callback does not require JWT (security fix verification)."""
        response = test_client.get(
            "/integrations/google/callback?code=test&state=invalid",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "oauth=error" in response.headers["location"]

    def test_callback_invalid_state(self, test_client):
        response = test_client.get(
            "/integrations/google/callback?code=test&state=invalid123",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "oauth=error" in response.headers["location"]

    def test_callback_expired_state(self, test_client, auth_headers, db):
        """A real state older than its 10 minutes is refused and consumed."""
        test_client.get("/integrations/google/auth", headers=auth_headers, follow_redirects=False)
        with db.write() as tx:
            tx.execute("UPDATE oauth_states SET expires_at = ?", (tx.ts(-1),))
        state = db.query_one("SELECT state FROM oauth_states")[0]

        response = test_client.get(
            f"/integrations/google/callback?code=test&state={state}",
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "oauth=error" in response.headers["location"]
        assert db.query_one("SELECT 1 FROM oauth_states") is None

    def test_callback_success_mocked(self, test_client, db, api_user):
        """Callback saves credentials for the state's user (token exchange mocked)."""
        from unittest.mock import Mock, patch

        mock_creds = Mock()
        mock_creds.token = "test_token"
        mock_creds.refresh_token = "test_refresh"
        mock_creds.scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
        mock_creds.expiry = None

        with patch(
            "selko.api.routes.integrations.complete_oauth_flow",
            return_value=(mock_creds, api_user, "gmail"),
        ), patch(
            "selko.api.routes.integrations.build_service",
            return_value=Mock(),
        ), patch(
            "selko.api.routes.integrations.get_user_profile",
            return_value={"emailAddress": "test@gmail.com"},
        ):
            response = test_client.get(
                "/integrations/google/callback?code=test_code&state=any",
                follow_redirects=False,
            )

        assert response.status_code == 302
        location = response.headers["location"]
        assert "oauth=success" in location
        assert "provider=gmail" in location
        row = db.query_one(
            "SELECT * FROM integrations WHERE user_id = ? AND provider = 'gmail'", (api_user,)
        )
        assert row["provider_email"] == "test@gmail.com"
        assert row["access_token"] == "test_token"


@pytest.mark.integration
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
        # No CORS headers needed for same-origin requests. This deliberately
        # asserts nothing about the health payload: the subject is CORS, and
        # /health's status reflects global work state that other tests perturb.
        assert "access-control-allow-origin" not in response.headers

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

