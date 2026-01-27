"""Unit tests for QuotaService."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from selko.services.quotas import (
    QuotaCheckResult,
    QuotaExceededError,
    QuotaService,
    UserUsage,
    get_quota_service,
)


class TestQuotaCheckResult:
    """Tests for QuotaCheckResult dataclass."""

    def test_quota_check_result_allowed(self):
        """Test creating an allowed quota result."""
        result = QuotaCheckResult(
            allowed=True,
            current_count=5,
            limit=100,
            remaining=95,
        )
        assert result.allowed is True
        assert result.current_count == 5
        assert result.limit == 100
        assert result.remaining == 95

    def test_quota_check_result_denied(self):
        """Test creating a denied quota result."""
        result = QuotaCheckResult(
            allowed=False,
            current_count=100,
            limit=100,
            remaining=0,
        )
        assert result.allowed is False
        assert result.current_count == 100
        assert result.remaining == 0

    def test_resets_at_returns_tomorrow_midnight_utc(self):
        """Test that resets_at returns tomorrow at midnight UTC."""
        result = QuotaCheckResult(
            allowed=True,
            current_count=1,
            limit=100,
            remaining=99,
        )
        resets_at = result.resets_at

        # Parse the ISO string
        reset_dt = datetime.fromisoformat(resets_at)

        # Should be tomorrow
        tomorrow = date.today() + timedelta(days=1)
        assert reset_dt.date() == tomorrow

        # Should be midnight (00:00:00)
        assert reset_dt.hour == 0
        assert reset_dt.minute == 0
        assert reset_dt.second == 0

        # Should be UTC
        assert reset_dt.tzinfo == timezone.utc


class TestQuotaExceededError:
    """Tests for QuotaExceededError exception."""

    def test_quota_exceeded_error_creation(self):
        """Test creating a quota exceeded error."""
        error = QuotaExceededError(
            quota_type="llm_calls",
            current_count=100,
            limit=100,
        )
        assert error.quota_type == "llm_calls"
        assert error.current_count == 100
        assert error.limit == 100
        assert "llm_calls" in str(error)
        assert "100/100" in str(error)

    def test_quota_exceeded_error_custom_message(self):
        """Test creating error with custom message."""
        error = QuotaExceededError(
            quota_type="email_syncs",
            current_count=50,
            limit=50,
            message="Custom error message",
        )
        assert error.message == "Custom error message"
        assert str(error) == "Custom error message"


class TestUserUsage:
    """Tests for UserUsage dataclass."""

    def test_user_usage_creation(self):
        """Test creating user usage object."""
        usage = UserUsage(
            llm_calls_count=10,
            llm_calls_limit=100,
            llm_calls_remaining=90,
            email_syncs_count=5,
            email_syncs_limit=50,
            email_syncs_remaining=45,
            calendar_syncs_count=2,
            calendar_syncs_limit=100,
            calendar_syncs_remaining=98,
        )
        assert usage.llm_calls_count == 10
        assert usage.llm_calls_limit == 100
        assert usage.llm_calls_remaining == 90
        assert usage.email_syncs_count == 5
        assert usage.calendar_syncs_remaining == 98


class TestQuotaService:
    """Tests for QuotaService."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Supabase client."""
        return MagicMock()

    @pytest.fixture
    def quota_service(self, mock_client):
        """Create a QuotaService with mock client."""
        return QuotaService(mock_client)

    def test_check_and_increment_allowed(self, quota_service, mock_client):
        """Test successful quota check and increment."""
        # Mock RPC response
        mock_client.rpc.return_value.execute.return_value.data = [
            {
                "allowed": True,
                "current_count": 1,
                "quota_limit": 100,
                "remaining": 99,
            }
        ]

        result = quota_service.check_and_increment("user-123", "llm_calls")

        assert result.allowed is True
        assert result.current_count == 1
        assert result.limit == 100
        assert result.remaining == 99

        # Verify RPC was called correctly
        mock_client.rpc.assert_called_once_with(
            "check_and_increment_quota",
            {
                "p_user_id": "user-123",
                "p_quota_type": "llm_calls",
                "p_increment": 1,
            },
        )

    def test_check_and_increment_denied(self, quota_service, mock_client):
        """Test quota check when limit exceeded."""
        mock_client.rpc.return_value.execute.return_value.data = [
            {
                "allowed": False,
                "current_count": 100,
                "quota_limit": 100,
                "remaining": 0,
            }
        ]

        result = quota_service.check_and_increment("user-123", "llm_calls")

        assert result.allowed is False
        assert result.current_count == 100
        assert result.remaining == 0

    def test_check_and_increment_custom_increment(self, quota_service, mock_client):
        """Test quota check with custom increment."""
        mock_client.rpc.return_value.execute.return_value.data = [
            {
                "allowed": True,
                "current_count": 10,
                "quota_limit": 100,
                "remaining": 90,
            }
        ]

        result = quota_service.check_and_increment("user-123", "email_syncs", increment=10)

        assert result.allowed is True
        mock_client.rpc.assert_called_once_with(
            "check_and_increment_quota",
            {
                "p_user_id": "user-123",
                "p_quota_type": "email_syncs",
                "p_increment": 10,
            },
        )

    def test_check_and_increment_empty_response(self, quota_service, mock_client):
        """Test handling of empty RPC response (fail-open)."""
        mock_client.rpc.return_value.execute.return_value.data = []

        result = quota_service.check_and_increment("user-123", "llm_calls")

        # Should allow request on empty response (fail-open)
        assert result.allowed is True

    def test_check_and_increment_error_handling(self, quota_service, mock_client):
        """Test error handling (fail-open for availability)."""
        mock_client.rpc.side_effect = Exception("Database error")

        result = quota_service.check_and_increment("user-123", "llm_calls")

        # Should allow request on error (fail-open)
        assert result.allowed is True
        assert result.limit == 100

    def test_get_usage_success(self, quota_service, mock_client):
        """Test getting user usage."""
        mock_client.rpc.return_value.execute.return_value.data = [
            {
                "llm_calls_count": 10,
                "llm_calls_limit": 100,
                "llm_calls_remaining": 90,
                "email_syncs_count": 5,
                "email_syncs_limit": 50,
                "email_syncs_remaining": 45,
                "calendar_syncs_count": 2,
                "calendar_syncs_limit": 100,
                "calendar_syncs_remaining": 98,
            }
        ]

        usage = quota_service.get_usage("user-123")

        assert usage.llm_calls_count == 10
        assert usage.email_syncs_remaining == 45
        assert usage.calendar_syncs_limit == 100

    def test_get_usage_with_date(self, quota_service, mock_client):
        """Test getting usage for specific date."""
        mock_client.rpc.return_value.execute.return_value.data = [
            {
                "llm_calls_count": 0,
                "llm_calls_limit": 100,
                "llm_calls_remaining": 100,
                "email_syncs_count": 0,
                "email_syncs_limit": 50,
                "email_syncs_remaining": 50,
                "calendar_syncs_count": 0,
                "calendar_syncs_limit": 100,
                "calendar_syncs_remaining": 100,
            }
        ]

        yesterday = date.today() - timedelta(days=1)
        usage = quota_service.get_usage("user-123", for_date=yesterday)

        mock_client.rpc.assert_called_once()
        call_args = mock_client.rpc.call_args
        assert call_args[0][1]["p_date"] == yesterday.isoformat()

    def test_get_usage_empty_response(self, quota_service, mock_client):
        """Test getting usage with no existing data."""
        mock_client.rpc.return_value.execute.return_value.data = []

        usage = quota_service.get_usage("user-123")

        # Should return defaults
        assert usage.llm_calls_count == 0
        assert usage.llm_calls_limit == 100
        assert usage.email_syncs_limit == 50

    def test_get_usage_error_handling(self, quota_service, mock_client):
        """Test error handling returns defaults."""
        mock_client.rpc.side_effect = Exception("Database error")

        usage = quota_service.get_usage("user-123")

        # Should return defaults on error
        assert usage.llm_calls_count == 0
        assert usage.llm_calls_limit == 100

    def test_set_user_limit_success(self, quota_service, mock_client):
        """Test setting custom user limit."""
        # Mock global limits check
        mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "max_allowed": 1000
        }
        # Mock upsert
        mock_client.table.return_value.upsert.return_value.execute.return_value = None

        quota_service.set_user_limit("user-123", "llm_calls", 500)

        # Verify upsert was called
        mock_client.table.return_value.upsert.assert_called_once()

    def test_set_user_limit_exceeds_max(self, quota_service, mock_client):
        """Test setting limit above max_allowed fails."""
        # Mock the select().eq().single().execute() chain
        mock_result = MagicMock()
        mock_result.data = {"max_allowed": 1000}
        mock_single = MagicMock()
        mock_single.execute.return_value = mock_result
        mock_eq = MagicMock()
        mock_eq.single.return_value = mock_single
        mock_select = MagicMock()
        mock_select.eq.return_value = mock_eq
        mock_table = MagicMock()
        mock_table.select.return_value = mock_select

        mock_client.table.return_value = mock_table

        with pytest.raises(ValueError, match="exceeds maximum"):
            quota_service.set_user_limit("user-123", "llm_calls", 2000)

    def test_set_user_limit_invalid_quota_type(self, quota_service, mock_client):
        """Test setting limit with invalid quota type."""
        with pytest.raises(ValueError, match="Invalid quota type"):
            quota_service.set_user_limit("user-123", "invalid_type", 100)


class TestGetQuotaService:
    """Tests for get_quota_service factory function."""

    def test_get_quota_service_returns_instance(self):
        """Test factory function returns QuotaService instance."""
        mock_client = MagicMock()
        service = get_quota_service(mock_client)

        assert isinstance(service, QuotaService)
        assert service.client == mock_client
