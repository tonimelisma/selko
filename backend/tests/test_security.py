"""Tests for security fixes: rate limiting, exception subclasses, alarmed fail-open."""

import time
from unittest.mock import MagicMock, patch

import pytest

from selko.services.emails import (
    EmailError,
    ExpiredCredentialsError,
    NoGmailIntegrationError,
)
from selko.services.quotas import QuotaCheckResult, QuotaService


class TestEmailExceptionSubclasses:
    """Test email exception hierarchy."""

    def test_no_gmail_integration_is_email_error(self):
        """NoGmailIntegrationError should be a subclass of EmailError."""
        error = NoGmailIntegrationError("No integration found")
        assert isinstance(error, EmailError)
        assert isinstance(error, NoGmailIntegrationError)

    def test_expired_credentials_is_email_error(self):
        """ExpiredCredentialsError should be a subclass of EmailError."""
        error = ExpiredCredentialsError("Credentials expired")
        assert isinstance(error, EmailError)
        assert isinstance(error, ExpiredCredentialsError)

    def test_catch_email_error_catches_subclasses(self):
        """Catching EmailError should also catch subclasses."""
        with pytest.raises(EmailError):
            raise NoGmailIntegrationError("test")

        with pytest.raises(EmailError):
            raise ExpiredCredentialsError("test")

    def test_catch_specific_does_not_catch_generic(self):
        """Catching a specific subclass should not catch generic EmailError."""
        with pytest.raises(EmailError):
            raise EmailError("generic error")

        # This should NOT raise NoGmailIntegrationError
        with pytest.raises(EmailError):
            raise EmailError("some other error")

    def test_fetch_emails_raises_no_integration(self):
        """fetch_emails_for_user should raise NoGmailIntegrationError when no creds."""
        from selko.services.emails import fetch_emails_for_user

        mock_client = MagicMock()
        mock_config = MagicMock()

        with patch("selko.services.emails.get_credentials", return_value=None):
            with pytest.raises(NoGmailIntegrationError, match="No Gmail integration"):
                fetch_emails_for_user(mock_client, mock_config)


class TestQuotaAlarmedFailOpen:
    """Test quota service alarmed fail-open behavior."""

    @pytest.fixture
    def mock_client(self):
        return MagicMock()

    @pytest.fixture
    def quota_service(self, mock_client):
        return QuotaService(mock_client)

    def test_error_allows_request(self, quota_service, mock_client):
        """On error, should allow request (fail-open)."""
        mock_client.rpc.side_effect = Exception("Database connection failed")

        result = quota_service.check_and_increment("user-123", "llm_calls")

        assert result.allowed is True

    def test_error_logs_structured_fields(self, quota_service, mock_client, caplog):
        """On error, should log with QUOTA_SERVICE_ERROR code."""
        mock_client.rpc.side_effect = Exception("Database connection failed")

        import logging
        with caplog.at_level(logging.ERROR):
            quota_service.check_and_increment("user-123", "llm_calls")

        assert "QUOTA_SERVICE_ERROR" in caplog.text

    def test_get_usage_error_logs_structured(self, quota_service, mock_client, caplog):
        """get_usage on error should log QUOTA_SERVICE_ERROR."""
        mock_client.rpc.side_effect = Exception("Connection timeout")

        import logging
        with caplog.at_level(logging.ERROR):
            usage = quota_service.get_usage("user-123")

        assert "QUOTA_SERVICE_ERROR" in caplog.text
        # Should still return defaults
        assert usage.llm_calls_count == 0
        assert usage.llm_calls_limit == 100


class TestOAuthCallbackRateLimiting:
    """Test IP-based rate limiting on OAuth callback endpoint."""

    def test_rate_limiter_allows_under_limit(self):
        """Requests under the limit should pass."""
        from selko.api.routes.integrations import (
            _callback_request_log,
            _check_callback_rate_limit,
        )

        # Clear any existing state
        _callback_request_log.clear()

        mock_request = MagicMock()
        mock_request.client.host = "192.168.1.100"

        # Should not raise for first request
        _check_callback_rate_limit(mock_request)

    def test_rate_limiter_blocks_over_limit(self):
        """Requests over the limit should be blocked with 429."""
        from fastapi import HTTPException

        from selko.api.routes.integrations import (
            _CALLBACK_RATE_LIMIT,
            _callback_request_log,
            _check_callback_rate_limit,
        )

        # Clear state and pre-fill with timestamps
        _callback_request_log.clear()
        now = time.monotonic()
        _callback_request_log["10.0.0.1"] = [now - i for i in range(_CALLBACK_RATE_LIMIT)]

        mock_request = MagicMock()
        mock_request.client.host = "10.0.0.1"

        with pytest.raises(HTTPException) as exc_info:
            _check_callback_rate_limit(mock_request)

        assert exc_info.value.status_code == 429

    def test_rate_limiter_separate_ips(self):
        """Different IPs should have separate rate limits."""
        from selko.api.routes.integrations import (
            _CALLBACK_RATE_LIMIT,
            _callback_request_log,
            _check_callback_rate_limit,
        )

        # Clear state
        _callback_request_log.clear()

        # Fill up IP A
        now = time.monotonic()
        _callback_request_log["ip-a"] = [now - i for i in range(_CALLBACK_RATE_LIMIT)]

        # IP B should still be allowed
        mock_request = MagicMock()
        mock_request.client.host = "ip-b"

        # Should not raise
        _check_callback_rate_limit(mock_request)

    def test_rate_limiter_expires_old_entries(self):
        """Entries older than the window should be cleaned up."""
        from selko.api.routes.integrations import (
            _CALLBACK_RATE_LIMIT,
            _CALLBACK_RATE_WINDOW,
            _callback_request_log,
            _check_callback_rate_limit,
        )

        # Clear state and add old timestamps (outside window)
        _callback_request_log.clear()
        now = time.monotonic()
        _callback_request_log["ip-old"] = [
            now - _CALLBACK_RATE_WINDOW - 10 for _ in range(_CALLBACK_RATE_LIMIT)
        ]

        mock_request = MagicMock()
        mock_request.client.host = "ip-old"

        # Should not raise because old entries are cleaned up
        _check_callback_rate_limit(mock_request)
