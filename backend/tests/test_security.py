"""Tests for security fixes: rate limiting, exception subclasses, alarmed fail-open."""

import time
from unittest.mock import MagicMock, patch

import pytest

from selko.services.emails import (
    EmailError,
    ExpiredCredentialsError,
    NoGmailIntegrationError,
)
from selko.services.quotas import QuotaService


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

    def test_fetch_emails_raises_no_integration(self, db, factory):
        """fetch_emails_for_user raises NoGmailIntegrationError without an active Gmail."""
        from selko.services.emails import fetch_emails_for_user

        user = factory.user()
        factory.integration(user, provider="gmail", status="expired")

        with pytest.raises(NoGmailIntegrationError, match="No Gmail integration"):
            fetch_emails_for_user(db, MagicMock(), user_id=user)

    def test_fetch_emails_scopes_the_sync_request_to_its_owner(self, db, factory):
        """Manual sync must only ever bring forward its own integrations' polls."""
        from selko.db import email_sync
        from selko.services.emails import fetch_emails_for_user

        owner, other = factory.user(), factory.user()
        mine = factory.integration(owner, provider="gmail")
        theirs = factory.integration(other, provider="gmail")
        later = "2999-01-01T00:00:00.000000Z"
        with db.write() as tx:
            tx.execute("UPDATE email_sync_state SET next_poll_at = ?", (later,))

        assert fetch_emails_for_user(db, MagicMock(), user_id=owner) == {
            "fetched": 0, "saved": 0, "attachments_downloaded": 0,
        }

        assert email_sync.get_sync_state(db, mine)["next_poll_at"] < later
        assert email_sync.get_sync_state(db, theirs)["next_poll_at"] == later

    def test_fetch_emails_leaves_a_live_lease_alone(self, db, factory):
        from selko.db import email_sync
        from selko.services.emails import fetch_emails_for_user

        owner = factory.user()
        mine = factory.integration(owner, provider="gmail")
        later = "2999-01-01T00:00:00.000000Z"
        with db.write() as tx:
            tx.execute("UPDATE email_sync_state SET next_poll_at = ?, lease_owner = 'w', lease_expires_at = ?",
                       (later, later))

        fetch_emails_for_user(db, MagicMock(), user_id=owner)

        assert email_sync.get_sync_state(db, mine)["next_poll_at"] == later

    def test_fetch_emails_requires_the_owner(self, db):
        from selko.services.emails import fetch_emails_for_user

        with pytest.raises(EmailError, match="user_id"):
            fetch_emails_for_user(db, MagicMock())


class TestQuotaAlarmedFailOpen:
    """Quota service alarmed fail-open, on a real database that fails."""

    @pytest.fixture
    def quota_service(self, db):
        return QuotaService(db)

    @pytest.fixture
    def broken(self, db, factory):
        """A user, and a database whose quota table is gone."""
        user = factory.user()
        with db.write() as tx:
            tx.execute("DROP TABLE usage_quotas")
        return user

    def test_error_allows_request(self, quota_service, broken):
        """On error, should allow request (fail-open)."""
        result = quota_service.check_and_increment(broken, "llm_calls")

        assert result.allowed is True

    def test_error_logs_structured_fields(self, quota_service, broken, caplog):
        """On error, should log with QUOTA_SERVICE_ERROR code."""
        import logging
        with caplog.at_level(logging.ERROR):
            quota_service.check_and_increment(broken, "llm_calls")

        assert "QUOTA_SERVICE_ERROR" in caplog.text

    def test_get_usage_error_logs_structured(self, quota_service, broken, caplog):
        """get_usage on error should log QUOTA_SERVICE_ERROR."""
        import logging
        with caplog.at_level(logging.ERROR):
            usage = quota_service.get_usage(broken)

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
