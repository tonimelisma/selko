"""Integration tests for FastAPI endpoints.

Tests API endpoints with real Supabase and JWT authentication.
"""

import pytest
from fastapi.testclient import TestClient

from selko.api.app import app
from selko.services.emails import save_emails


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

    def test_emails_no_auth(self, test_client):
        """GET /emails without auth returns 401."""
        response = test_client.get("/emails")

        assert response.status_code == 401
        assert "Missing Authorization header" in response.json()["detail"]

    def test_emails_invalid_auth(self, test_client):
        """GET /emails with invalid token returns 401."""
        response = test_client.get(
            "/emails", headers={"Authorization": "Bearer invalid_token"}
        )

        assert response.status_code == 401
        assert "Invalid or expired token" in response.json()["detail"]

    def test_emails_malformed_auth(self, test_client):
        """GET /emails with malformed header returns 401."""
        response = test_client.get("/emails", headers={"Authorization": "NotBearer"})

        assert response.status_code == 401
        assert "Invalid Authorization header format" in response.json()["detail"]

    def test_integrations_no_auth(self, test_client):
        """GET /integrations without auth returns 401."""
        response = test_client.get("/integrations")

        assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.development
class TestEmailEndpoints:
    """Test email endpoints with authentication."""

    def test_list_emails_empty(self, test_client, auth_headers):
        """GET /emails returns empty list when no emails."""
        response = test_client.get("/emails", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "offset" in data
        assert "limit" in data
        assert data["offset"] == 0
        assert data["limit"] == 20

    def test_list_emails_with_data(
        self,
        test_client,
        auth_headers,
        authenticated_client,
        sample_email_data,
        cleanup_emails,
    ):
        """GET /emails returns emails for authenticated user."""
        # Save test email
        cleanup_emails.append(sample_email_data["gmail_id"])
        saved = save_emails(authenticated_client, [sample_email_data])
        email_id = saved[0]["id"]

        # Verify list endpoint works and returns data
        response = test_client.get("/emails", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

        # Verify we can fetch the specific email by ID
        response = test_client.get(f"/emails/{email_id}", headers=auth_headers)
        assert response.status_code == 200
        email_data = response.json()
        assert email_data["gmail_id"] == sample_email_data["gmail_id"]
        assert email_data["subject"] == sample_email_data["subject"]

    def test_list_emails_pagination(
        self,
        test_client,
        auth_headers,
        authenticated_client,
        cleanup_emails,
    ):
        """GET /emails with pagination parameters."""
        from uuid import uuid4

        # Create multiple emails
        for i in range(5):
            gmail_id = f"test_page_{uuid4().hex[:8]}"
            cleanup_emails.append(gmail_id)
            save_emails(
                authenticated_client,
                [
                    {
                        "gmail_id": gmail_id,
                        "thread_id": f"thread_{i}",
                        "subject": f"Pagination test {i}",
                        "from_email": "test@example.com",
                        "gmail_label_ids": ["INBOX"],
                        "date_sent": f"2026-01-22T{10+i:02d}:00:00+00:00",
                    }
                ],
            )

        # Test pagination
        response = test_client.get(
            "/emails?offset=0&limit=2", headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["offset"] == 0
        assert data["limit"] == 2
        assert len(data["items"]) <= 2

    def test_get_email_by_id(
        self,
        test_client,
        auth_headers,
        authenticated_client,
        sample_email_data,
        cleanup_emails,
    ):
        """GET /emails/{id} returns specific email."""
        cleanup_emails.append(sample_email_data["gmail_id"])
        saved = save_emails(authenticated_client, [sample_email_data])
        email_id = saved[0]["id"]

        response = test_client.get(f"/emails/{email_id}", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == email_id
        assert data["subject"] == sample_email_data["subject"]

    def test_get_email_not_found(self, test_client, auth_headers):
        """GET /emails/{id} returns 404 for non-existent email."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = test_client.get(f"/emails/{fake_id}", headers=auth_headers)

        assert response.status_code == 404
        assert "Email not found" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.development
class TestIntegrationEndpoints:
    """Test integration endpoints with authentication."""

    def test_list_integrations_empty(self, test_client, auth_headers):
        """GET /integrations returns empty list when no integrations."""
        response = test_client.get("/integrations", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_list_integrations_with_data(
        self,
        test_client,
        config,
        sample_oauth_credentials,
        temp_user_client,
    ):
        """GET /integrations returns integrations for user."""
        from selko.services.auth import get_current_user_id
        from selko.services.integrations import save_oauth_credentials

        # Use temp user to avoid interfering with seeded credentials
        # Get auth token for temp user
        session = temp_user_client.auth.get_session()
        headers = {"Authorization": f"Bearer {session.access_token}"}

        # Save test integration
        user_id = get_current_user_id(temp_user_client)
        save_oauth_credentials(
            temp_user_client, user_id, "gmail", sample_oauth_credentials, "test@gmail.com"
        )

        response = test_client.get("/integrations", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

        integration = next((i for i in data if i["provider"] == "gmail"), None)
        assert integration is not None
        assert integration["status"] == "active"
        assert integration["provider_email"] == "test@gmail.com"

        # Verify sensitive fields are excluded
        assert "access_token" not in integration
        assert "refresh_token" not in integration

    def test_get_integration_by_provider(
        self,
        test_client,
        config,
        sample_oauth_credentials,
        temp_user_client,
    ):
        """GET /integrations/{provider} returns specific integration."""
        from selko.services.auth import get_current_user_id
        from selko.services.integrations import save_oauth_credentials

        # Use temp user to avoid interfering with seeded credentials
        # Get auth token for temp user
        session = temp_user_client.auth.get_session()
        headers = {"Authorization": f"Bearer {session.access_token}"}

        user_id = get_current_user_id(temp_user_client)
        save_oauth_credentials(
            temp_user_client, user_id, "gmail", sample_oauth_credentials, "test@gmail.com"
        )

        response = test_client.get("/integrations/gmail", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["provider"] == "gmail"
        assert data["status"] == "active"

    def test_get_integration_not_found(self, test_client, auth_headers):
        """GET /integrations/{provider} returns 404 for non-existent."""
        response = test_client.get("/integrations/google_photos", headers=auth_headers)

        assert response.status_code == 404
        assert "No google_photos integration found" in response.json()["detail"]

    def test_get_integration_invalid_provider(self, test_client, auth_headers):
        """GET /integrations/{provider} returns 400 for invalid provider."""
        response = test_client.get("/integrations/invalid_provider", headers=auth_headers)

        assert response.status_code == 400
        assert "Invalid provider" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.development
class TestNewEmailEndpoints:
    """Test new email operation endpoints (Phase 1)."""

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
class TestIntegrationManagementEndpoints:
    """Test integration management endpoints (Phase 2)."""

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

    def test_disconnect_integration_invalid_provider(self, test_client, auth_headers):
        """DELETE /integrations/{provider} validates provider."""
        response = test_client.delete(
            "/integrations/invalid_provider", headers=auth_headers
        )

        assert response.status_code == 400
        assert "Invalid provider" in response.json()["detail"]

    def test_disconnect_integration_not_found(self, test_client, auth_headers):
        """DELETE /integrations/{provider} succeeds even if not found."""
        # Deleting non-existent integration should be idempotent
        response = test_client.delete("/integrations/google_photos", headers=auth_headers)

        # Should return 204 No Content
        assert response.status_code == 204


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
        assert "Invalid or expired state" in response.json()["detail"]

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
class TestAttachmentEndpoints:
    """Test attachment endpoints (Phase 3)."""

    def test_get_attachment_not_found(self, test_client, auth_headers):
        """GET /attachments/{id} returns 404 for non-existent attachment."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = test_client.get(f"/attachments/{fake_id}", headers=auth_headers)

        assert response.status_code == 404
        assert "Attachment not found" in response.json()["detail"]

    def test_download_attachment_not_found(self, test_client, auth_headers):
        """GET /attachments/{id}/download returns 404 for non-existent attachment."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = test_client.get(f"/attachments/{fake_id}/download", headers=auth_headers)

        assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.development
class TestEventSyncEndpoint:
    """Test event sync endpoint (Phase 4)."""

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
class TestRLSSecurity:
    """Test that RLS properly isolates user data via API."""

    def test_cannot_access_other_users_emails(
        self,
        test_client,
        auth_headers,
        admin_client,
        test_user_id,
        temp_user,
    ):
        """API enforces RLS - cannot access emails from other users."""
        from uuid import uuid4

        # Use temp_user (a real user) for the other user
        other_user_id, _, _ = temp_user
        gmail_id = f"test_rls_api_{uuid4().hex[:8]}"

        # Create an email belonging to the other user via admin client
        admin_client.table("emails").insert(
            {
                "user_id": other_user_id,
                "gmail_id": gmail_id,
                "thread_id": "other_thread",
                "subject": "Other user email",
                "from_email": "other@example.com",
                "gmail_label_ids": ["INBOX"],
            }
        ).execute()

        try:
            # Try to access via API - should not find it
            response = test_client.get("/emails", headers=auth_headers)

            assert response.status_code == 200
            data = response.json()

            # Our user should not see the other user's email
            found_emails = [e for e in data["items"] if e["gmail_id"] == gmail_id]
            assert len(found_emails) == 0

        finally:
            # Cleanup via admin
            admin_client.table("emails").delete().eq("gmail_id", gmail_id).execute()
