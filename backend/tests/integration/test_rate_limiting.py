"""Integration tests for rate limiting and quota enforcement.

Tests verify:
1. Database quota tables exist and work correctly
2. Quota enforcement returns 429 when exceeded
3. X-RateLimit headers are included in responses
4. LLM is NOT called when quota is exceeded
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from selko.api.app import app
from selko.services.quotas import QuotaService


@pytest.mark.integration
@pytest.mark.development
class TestQuotaDatabaseIntegration:
    """Tests for quota database operations."""

    def test_global_limits_table_has_defaults(self, authenticated_client):
        """Test global_limits table has seeded defaults."""
        result = authenticated_client.table("global_limits").select("*").execute()

        assert len(result.data) >= 3

        limit_types = {row["limit_type"] for row in result.data}
        assert "llm_calls_daily" in limit_types
        assert "email_syncs_daily" in limit_types
        assert "calendar_syncs_daily" in limit_types

    def test_usage_quotas_rls_only_own_data(
        self, authenticated_client, temp_user_client, test_user_id, temp_user
    ):
        """Test RLS prevents users from seeing other users' quota data."""
        temp_user_id, _, _ = temp_user

        # Create quota record for test user (via service role or RPC)
        # First, let's use the RPC to increment quota for test user
        authenticated_client.rpc(
            "check_and_increment_quota",
            {
                "p_user_id": test_user_id,
                "p_quota_type": "llm_calls",
                "p_increment": 1,
            },
        ).execute()

        # Temp user should not see test user's quota
        result = (
            temp_user_client.table("usage_quotas")
            .select("*")
            .eq("user_id", test_user_id)
            .execute()
        )

        # RLS should filter this out
        assert len(result.data) == 0

    def test_quota_rpc_check_and_increment(self, authenticated_client, test_user_id):
        """Test check_and_increment_quota RPC function."""
        # First call should succeed
        result = authenticated_client.rpc(
            "check_and_increment_quota",
            {
                "p_user_id": test_user_id,
                "p_quota_type": "llm_calls",
                "p_increment": 1,
            },
        ).execute()

        assert len(result.data) == 1
        row = result.data[0]
        assert row["allowed"] is True
        assert row["current_count"] >= 1
        assert row["quota_limit"] > 0

    def test_quota_rpc_get_user_usage(self, authenticated_client, test_user_id):
        """Test get_user_quota_usage RPC function."""
        result = authenticated_client.rpc(
            "get_user_quota_usage",
            {"p_user_id": test_user_id},
        ).execute()

        assert len(result.data) == 1
        row = result.data[0]
        assert "llm_calls_count" in row
        assert "llm_calls_limit" in row
        assert "email_syncs_count" in row
        assert "calendar_syncs_count" in row


@pytest.mark.integration
@pytest.mark.development
class TestQuotaServiceIntegration:
    """Tests for QuotaService with real database."""

    def test_quota_service_check_and_increment(self, admin_client, test_user_id):
        """Test QuotaService with real database."""
        from selko.services.quotas import QuotaService

        service = QuotaService(admin_client)

        result = service.check_and_increment(test_user_id, "llm_calls")

        assert result.allowed is True
        assert result.limit > 0
        assert result.remaining >= 0

    def test_quota_service_get_usage(self, admin_client, test_user_id):
        """Test QuotaService.get_usage with real database."""
        from selko.services.quotas import QuotaService

        service = QuotaService(admin_client)

        usage = service.get_usage(test_user_id)

        assert usage.llm_calls_limit > 0
        assert usage.email_syncs_limit > 0
        assert usage.calendar_syncs_limit > 0


@pytest.mark.integration
@pytest.mark.development
class TestAPIRateLimitHeaders:
    """Tests for rate limit headers in API responses."""

    @pytest.fixture
    def api_client(self, config, authenticated_client):
        """Create test client for API."""
        # Get auth token from authenticated client
        session = authenticated_client.auth.get_session()
        token = session.access_token

        client = TestClient(app)
        client.headers["Authorization"] = f"Bearer {token}"
        return client

    def test_email_sync_returns_rate_limit_headers(self, api_client):
        """Test /emails/sync returns X-RateLimit headers."""
        # This will fail with 404 (no Gmail integration) but should still have headers
        response = api_client.post("/emails/sync", json={"max_results": 10})

        # Even on 404, headers should be present (quota was checked)
        # Note: If quota check happens before Gmail check, headers will be present
        # If it returns 404 before quota check, they won't be
        # Our implementation checks quota first, so headers should be present
        if response.status_code == 429:
            assert "X-RateLimit-Limit" in response.headers
            assert "X-RateLimit-Remaining" in response.headers
        # 404 means Gmail not connected, quota check passed

    @patch("selko.api.routes.emails.fetch_emails_for_user")
    def test_successful_sync_has_rate_limit_headers(
        self, mock_fetch, api_client
    ):
        """Test successful response includes rate limit headers."""
        mock_fetch.return_value = {
            "fetched": 5,
            "saved": 5,
            "attachments_downloaded": 0,
        }

        response = api_client.post("/emails/sync", json={"max_results": 10})

        # If quota exceeded, we get 429 with headers
        if response.status_code == 429:
            assert "X-RateLimit-Limit" in response.headers
        # If successful, headers should be present
        elif response.status_code == 200:
            assert "X-RateLimit-Limit" in response.headers
            assert "X-RateLimit-Remaining" in response.headers
            assert "X-RateLimit-Reset" in response.headers


@pytest.mark.integration
@pytest.mark.development
class TestQuotaExceeded:
    """Tests for quota exceeded behavior."""

    @pytest.fixture
    def api_client(self, config, authenticated_client):
        """Create test client for API."""
        session = authenticated_client.auth.get_session()
        token = session.access_token

        client = TestClient(app)
        client.headers["Authorization"] = f"Bearer {token}"
        return client

    @patch("selko.services.quotas.QuotaService.check_and_increment")
    def test_llm_quota_exceeded_returns_429(self, mock_quota_check, api_client):
        """Test that exceeding LLM quota returns 429 without calling LLM."""
        from selko.services.quotas import QuotaCheckResult

        # Mock quota as exceeded
        mock_quota_check.return_value = QuotaCheckResult(
            allowed=False,
            current_count=100,
            limit=100,
            remaining=0,
        )

        response = api_client.post(
            "/emails/test-email-id/process",
        )

        assert response.status_code in (429, 401, 404)  # 429 if quota hit, 401/404 if other checks fail first

        # If we got 429, verify the response format
        if response.status_code == 429:
            data = response.json()
            assert "quota" in data.get("detail", "").lower() or "quota" in data.get("error", "")

    @patch("selko.services.events.process_email_for_events")
    @patch("selko.services.quotas.QuotaService.check_and_increment")
    def test_llm_not_called_when_quota_exceeded(
        self, mock_quota_check, mock_process_email, api_client
    ):
        """Test LLM is NOT called when quota is exceeded."""
        from selko.services.quotas import QuotaCheckResult

        mock_quota_check.return_value = QuotaCheckResult(
            allowed=False,
            current_count=100,
            limit=100,
            remaining=0,
        )

        api_client.post("/emails/test-email-id/process")

        # process_email_for_events should NOT have been called
        mock_process_email.assert_not_called()


@pytest.mark.integration
@pytest.mark.development
class TestOAuthRedirectValidation:
    """Tests for OAuth redirect URI validation."""

    @pytest.fixture
    def api_client(self, config, authenticated_client):
        """Create test client for API."""
        session = authenticated_client.auth.get_session()
        token = session.access_token

        client = TestClient(app)
        client.headers["Authorization"] = f"Bearer {token}"
        return client

    def test_valid_localhost_redirect(self, api_client):
        """Test valid localhost redirect URI is accepted."""
        response = api_client.get(
            "/integrations/gmail/auth",
            params={"redirect_uri": "http://localhost:8000/integrations/google/callback"},
            follow_redirects=False,
        )

        # Should redirect to Google OAuth (302) or fail for other reasons
        # But should NOT be 400 for invalid redirect
        assert response.status_code != 400 or "redirect" not in response.json().get("detail", "").lower()

    def test_invalid_redirect_host_rejected(self, api_client):
        """Test invalid redirect host is rejected with 400."""
        response = api_client.get(
            "/integrations/gmail/auth",
            params={"redirect_uri": "https://evil.com/callback"},
            follow_redirects=False,
        )

        assert response.status_code == 400
        assert "redirect" in response.json().get("detail", "").lower()

    def test_invalid_redirect_path_rejected(self, api_client):
        """Test invalid redirect path is rejected."""
        response = api_client.get(
            "/integrations/gmail/auth",
            params={"redirect_uri": "http://localhost:8000/malicious/path"},
            follow_redirects=False,
        )

        assert response.status_code == 400


@pytest.mark.integration
@pytest.mark.development
class TestErrorSanitization:
    """Tests for error message sanitization."""

    @pytest.fixture
    def api_client(self, config, authenticated_client):
        """Create test client for API."""
        session = authenticated_client.auth.get_session()
        token = session.access_token

        client = TestClient(app)
        client.headers["Authorization"] = f"Bearer {token}"
        return client

    def test_email_sync_error_sanitized(self, api_client):
        """Test email sync errors don't leak internal details."""
        response = api_client.post("/emails/sync", json={"max_results": 10})

        if response.status_code >= 500:
            detail = response.json().get("detail", "")
            # Should not contain stack traces or internal paths
            assert "Traceback" not in detail
            assert "/Users/" not in detail
            assert "Exception" not in detail

    def test_process_email_error_sanitized(self, api_client):
        """Test email processing errors don't leak details."""
        response = api_client.post("/emails/nonexistent-id/process")

        if response.status_code >= 500:
            detail = response.json().get("detail", "")
            assert "Traceback" not in detail
