"""Unit tests for QuotaService."""

from datetime import date, datetime, timedelta, timezone

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


def _break_quota_tables(db):
    """A real database failure: the quota table is gone."""
    with db.write() as tx:
        tx.execute("DROP TABLE usage_quotas")


class TestQuotaService:
    """QuotaService over a real SQLite database (seeded global_limits)."""

    @pytest.fixture
    def quota_service(self, db):
        return QuotaService(db)

    def test_check_and_increment_allowed(self, quota_service, factory):
        user = factory.user()
        result = quota_service.check_and_increment(user, "llm_calls")
        assert result == QuotaCheckResult(allowed=True, current_count=1, limit=100, remaining=99)
        again = quota_service.check_and_increment(user, "llm_calls")
        assert again.current_count == 2

    def test_check_and_increment_denied_changes_nothing(self, quota_service, factory, db):
        user = factory.user()
        quota_service.set_user_limit(user, "email_syncs", 2)
        assert quota_service.check_and_increment(user, "email_syncs", 2).allowed
        denied = quota_service.check_and_increment(user, "email_syncs")
        assert denied == QuotaCheckResult(allowed=False, current_count=2, limit=2, remaining=0)
        assert db.query_one("SELECT email_syncs_count FROM usage_quotas WHERE user_id = ?", (user,))[0] == 2

    def test_check_and_increment_custom_increment(self, quota_service, factory):
        result = quota_service.check_and_increment(factory.user(), "calendar_syncs", increment=5)
        assert (result.allowed, result.current_count, result.remaining) == (True, 5, 95)

    def test_quotas_are_per_user(self, quota_service, factory):
        alice, bob = factory.user(), factory.user()
        quota_service.check_and_increment(alice, "llm_calls", 10)
        assert quota_service.check_and_increment(bob, "llm_calls").current_count == 1

    def test_check_and_increment_error_fails_open(self, quota_service, factory, db):
        user = factory.user()
        _break_quota_tables(db)
        result = quota_service.check_and_increment(user, "llm_calls")
        assert result.allowed is True
        assert result.current_count == 0

    def test_get_usage_success(self, quota_service, factory):
        user = factory.user()
        quota_service.check_and_increment(user, "llm_calls", 3)
        usage = quota_service.get_usage(user)
        assert usage == UserUsage(
            llm_calls_count=3, llm_calls_limit=100, llm_calls_remaining=97,
            email_syncs_count=0, email_syncs_limit=50, email_syncs_remaining=50,
            calendar_syncs_count=0, calendar_syncs_limit=100, calendar_syncs_remaining=100,
        )

    def test_get_usage_with_date_reads_that_day(self, quota_service, factory):
        user = factory.user()
        quota_service.check_and_increment(user, "llm_calls", 3)
        usage = quota_service.get_usage(user, for_date=date(2020, 1, 1))
        assert usage.llm_calls_count == 0
        assert usage.llm_calls_limit == 100

    def test_get_usage_error_returns_defaults(self, quota_service, factory, db):
        user = factory.user()
        _break_quota_tables(db)
        usage = quota_service.get_usage(user)
        assert usage.llm_calls_count == 0
        assert usage.llm_calls_limit == 100

    def test_set_user_limit_success(self, quota_service, factory, db):
        user = factory.user()
        quota_service.set_user_limit(user, "llm_calls", 500)
        row = db.query_one("SELECT llm_calls_limit, email_syncs_limit FROM usage_quotas WHERE user_id = ?", (user,))
        assert (row[0], row[1]) == (500, 50), "only the named limit changes"
        quota_service.set_user_limit(user, "llm_calls", 600)
        assert quota_service.check_and_increment(user, "llm_calls").limit == 600

    def test_set_user_limit_exceeds_max(self, quota_service, factory):
        with pytest.raises(ValueError, match="exceeds maximum"):
            quota_service.set_user_limit(factory.user(), "llm_calls", 2000)

    def test_set_user_limit_without_a_global_max_is_allowed(self, quota_service, factory, db):
        """As before: when the maximum cannot be verified, the limit is set."""
        user = factory.user()
        with db.write() as tx:
            tx.execute("DELETE FROM global_limits WHERE limit_type = 'llm_calls_daily'")
        quota_service.set_user_limit(user, "llm_calls", 5000)
        assert db.query_one("SELECT llm_calls_limit FROM usage_quotas WHERE user_id = ?", (user,))[0] == 5000

    def test_set_user_limit_invalid_quota_type(self, quota_service):
        with pytest.raises(ValueError, match="Invalid quota type"):
            quota_service.set_user_limit("user-123", "invalid_type", 100)


class TestGetQuotaService:
    """Tests for get_quota_service factory function."""

    def test_get_quota_service_returns_instance(self, db):
        service = get_quota_service(db)

        assert isinstance(service, QuotaService)
        assert service.client is db
