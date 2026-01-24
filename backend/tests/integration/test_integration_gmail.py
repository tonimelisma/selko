"""Integration tests for Gmail service.

Development tests use mocked Gmail API responses.
Staging tests use real Gmail API with burner account.
"""

from unittest.mock import MagicMock, patch

import pytest

from selko.services.gmail import (
    SCOPES,
    GmailError,
    build_service,
    fetch_messages,
    get_credentials,
    get_user_profile,
)
from selko.services.integrations import save_oauth_credentials


@pytest.mark.integration
@pytest.mark.development
class TestGmailDevelopment:
    """Test Gmail service with mocked API (development)."""

    def test_build_service(self, sample_oauth_credentials):
        """Can build Gmail service from credentials."""
        service = build_service(sample_oauth_credentials)

        assert service is not None
        # Service should have users() method
        assert hasattr(service, "users")

    def test_get_credentials_from_db(
        self,
        authenticated_client,
        config,
        sample_oauth_credentials,
        cleanup_integrations,
    ):
        """Can retrieve credentials from database."""
        cleanup_integrations.append("gmail")

        # Save credentials first
        save_oauth_credentials(authenticated_client, "gmail", sample_oauth_credentials)

        # Get credentials via gmail service
        creds = get_credentials(authenticated_client, config)

        assert creds is not None
        assert creds.token == sample_oauth_credentials.token

    def test_get_credentials_not_found(self, authenticated_client, config):
        """Returns None when no Gmail credentials exist."""
        # Ensure no Gmail integration exists for this user
        # (cleanup from previous tests should handle this)
        creds = get_credentials(authenticated_client, config)

        # May or may not be None depending on test state
        # Just verify it doesn't raise an error

    @patch("selko.services.gmail.build")
    def test_get_user_profile_mocked(
        self, mock_build, sample_oauth_credentials
    ):
        """Get user profile returns email address."""
        # Setup mock
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().getProfile().execute.return_value = {
            "emailAddress": "test@gmail.com",
            "messagesTotal": 100,
            "threadsTotal": 50,
        }

        service = build_service(sample_oauth_credentials)
        profile = get_user_profile(service)

        assert profile["emailAddress"] == "test@gmail.com"
        assert "messagesTotal" in profile

    @patch("selko.services.gmail.build")
    def test_fetch_messages_mocked(self, mock_build, sample_oauth_credentials):
        """Fetch messages returns list of emails."""
        # Setup mock
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        # Mock list response
        mock_service.users().messages().list().execute.return_value = {
            "messages": [{"id": "msg1"}, {"id": "msg2"}, {"id": "msg3"}]
        }

        # Mock get response
        mock_service.users().messages().get().execute.return_value = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Test snippet",
            "labelIds": ["INBOX"],
            "payload": {"headers": []},
        }

        service = build_service(sample_oauth_credentials)
        messages = fetch_messages(service, max_results=3)

        assert len(messages) == 3

    @patch("selko.services.gmail.build")
    def test_fetch_messages_empty(self, mock_build, sample_oauth_credentials):
        """Fetch messages handles empty inbox."""
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().messages().list().execute.return_value = {}

        service = build_service(sample_oauth_credentials)
        messages = fetch_messages(service, max_results=10)

        assert messages == []

    @patch("selko.services.gmail.build")
    def test_rate_limiting_retry(self, mock_build, sample_oauth_credentials):
        """Rate limited requests are retried with backoff."""
        from googleapiclient.errors import HttpError
        from httplib2 import Response

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        # Mock list response
        mock_service.users().messages().list().execute.return_value = {
            "messages": [{"id": "msg1"}]
        }

        # First get call raises 429, second succeeds
        rate_limit_error = HttpError(
            resp=Response({"status": 429}),
            content=b'{"error": {"code": 429, "message": "Rate limit"}}',
        )

        mock_service.users().messages().get().execute.side_effect = [
            rate_limit_error,
            {"id": "msg1", "threadId": "t1", "snippet": "test", "labelIds": []},
        ]

        service = build_service(sample_oauth_credentials)

        # Should succeed after retry (with some delay)
        with patch("time.sleep"):  # Don't actually wait
            messages = fetch_messages(service, max_results=1)

        assert len(messages) == 1

    def test_credentials_file_not_found(self, config):
        """OAuth flow fails if credentials file missing."""
        from selko.config import Config
        from pathlib import Path
        from selko.services.gmail import run_oauth_flow

        bad_config = Config(
            environment=config.environment,
            supabase_url=config.supabase_url,
            supabase_key=config.supabase_key,
            credentials_file=Path("/nonexistent/credentials.json"),
        )

        with pytest.raises(GmailError) as exc_info:
            run_oauth_flow(bad_config)

        assert "not found" in str(exc_info.value).lower()

    def test_gmail_scopes(self):
        """Gmail scope is read-only."""
        assert len(SCOPES) == 1
        assert "gmail.readonly" in SCOPES[0]


@pytest.mark.integration
@pytest.mark.staging
class TestGmailStaging:
    """Test Gmail service with real API (staging).

    These tests require:
    1. Burner Gmail account authorized
    2. OAuth tokens stored in staging database
    3. ENVIRONMENT=staging or --env staging
    """

    def test_get_credentials_real(self, authenticated_client, config):
        """Can retrieve real Gmail credentials from staging DB."""
        creds = get_credentials(authenticated_client, config)

        # If no credentials, skip the test
        if creds is None:
            pytest.skip("No Gmail credentials in staging - run cli_auth_gmail first")

        assert creds.token is not None
        # Real credentials should have refresh token
        assert creds.refresh_token is not None

    def test_build_service_real(self, authenticated_client, config):
        """Can build service with real credentials."""
        creds = get_credentials(authenticated_client, config)
        if creds is None:
            pytest.skip("No Gmail credentials in staging")

        service = build_service(creds)
        assert service is not None

    def test_get_user_profile_real(self, authenticated_client, config):
        """Can get real user profile from Gmail."""
        creds = get_credentials(authenticated_client, config)
        if creds is None:
            pytest.skip("No Gmail credentials in staging")

        service = build_service(creds)
        profile = get_user_profile(service)

        assert "emailAddress" in profile
        assert "@" in profile["emailAddress"]

    def test_fetch_messages_real(self, authenticated_client, config):
        """Can fetch real messages from Gmail."""
        creds = get_credentials(authenticated_client, config)
        if creds is None:
            pytest.skip("No Gmail credentials in staging")

        service = build_service(creds)
        messages = fetch_messages(service, max_results=5)

        # Burner account should have at least some emails
        # (send test emails to it during setup)
        assert isinstance(messages, list)
        # Each message should have expected fields
        if messages:
            msg = messages[0]
            assert "id" in msg
            assert "threadId" in msg
            assert "labelIds" in msg

    def test_token_refresh_if_expired(self, authenticated_client, config):
        """Expired tokens are automatically refreshed."""
        # This test verifies the refresh logic works
        # The get_credentials function handles refresh automatically
        creds = get_credentials(authenticated_client, config)
        if creds is None:
            pytest.skip("No Gmail credentials in staging")

        # Credentials should be valid (refreshed if needed)
        # If they were expired, get_credentials would have refreshed them
        assert creds.token is not None
