"""Unit tests for reliability improvements.

Tests exponential backoff, circuit breaker, dead-letter pattern,
and timeout handling.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from selko.services.circuit_breaker import CircuitBreaker, CircuitState

FROZEN_NOW = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)


class FrozenRetryDateTime(datetime):
    """Controllable datetime shim for retry delay tests."""

    frozen_now = FROZEN_NOW

    @classmethod
    def now(cls, tz=None):
        now = cls.frozen_now
        return now if tz is None else now.astimezone(tz)


class FakeClock:
    """Simple monotonic clock for circuit-breaker tests."""

    def __init__(self, start: float = 0.0):
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def freeze_retry_clock(now: datetime = FROZEN_NOW):
    FrozenRetryDateTime.frozen_now = now
    return patch("selko.services.retry_utils.datetime", FrozenRetryDateTime)


# ===========================================================================
# Exponential Backoff Tests
# ===========================================================================


def _email_pool(pool, attempts: int, max_attempts: int):
    """Queue the attempts row for the SELECT and record the UPDATE."""
    pool.rows.append({"attempts": attempts, "max_attempts": max_attempts})
    return pool


def _last_update_args(pool) -> tuple:
    """Args of the last UPDATE executed against the pool."""
    for sql, args in reversed(pool.calls):
        if "UPDATE" in sql:
            return args
    raise AssertionError("no UPDATE call recorded")


class TestExponentialBackoff:
    @pytest.fixture(autouse=True)
    def pool(self, fake_pg_pool):
        self.pool = fake_pg_pool

    """Tests for exponential backoff calculation in fail_email_processing."""

    def test_first_retry_delay_60s(self):
        """First retry (attempt 1) should have 60s delay."""
        import asyncio

        from selko.services.emails import fail_email_processing

        pool = _email_pool(self.pool, attempts=1, max_attempts=3)
        with freeze_retry_clock():
            asyncio.run(fail_email_processing(pool, "email-1", "test error"))

        sql, args = pool.calls[-1]
        assert "processing_status = 'pending'" in sql
        assert "next_retry_at = $3" in sql
        assert args[2] == FROZEN_NOW + timedelta(seconds=60)

    def test_second_retry_delay_120s(self):
        """Second retry (attempt 2) should have 120s delay."""
        import asyncio

        from selko.services.emails import fail_email_processing

        pool = _email_pool(self.pool, attempts=2, max_attempts=3)
        with freeze_retry_clock():
            asyncio.run(fail_email_processing(pool, "email-1", "test error"))

        sql, args = pool.calls[-1]
        assert "processing_status = 'pending'" in sql
        assert args[2] == FROZEN_NOW + timedelta(seconds=120)

    def test_delay_capped_at_3600s(self):
        """Delay should be capped at 3600s (1 hour) for high attempt counts."""
        import asyncio

        from selko.services.emails import fail_email_processing

        # Attempt 7 would be 60 * 2^6 = 3840, but should be capped at 3600
        pool = _email_pool(self.pool, attempts=7, max_attempts=10)
        with freeze_retry_clock():
            asyncio.run(fail_email_processing(pool, "email-1", "test error"))

        sql, args = pool.calls[-1]
        assert args[2] == FROZEN_NOW + timedelta(seconds=3600)

    def test_backoff_doubles_each_attempt(self):
        """Verify delay doubles exactly with each attempt until the cap."""
        import asyncio

        from selko.services.emails import fail_email_processing

        delays = []
        for attempt in [1, 2, 3, 4]:
            pool = _email_pool(self.pool, attempts=attempt, max_attempts=5)
            with freeze_retry_clock():
                asyncio.run(fail_email_processing(pool, f"email-{attempt}", "test error"))
            sql, args = pool.calls[-1]
            delays.append(int((args[2] - FROZEN_NOW).total_seconds()))
            self.pool.calls.clear()
            self.pool.rows.clear()

        assert delays == [60, 120, 240, 480]


class TestExponentialBackoffEvents:
    @pytest.fixture(autouse=True)
    def pool(self, fake_pg_pool):
        self.pool = fake_pg_pool

    """Tests for exponential backoff in fail_event_sync."""

    def test_event_retry_with_backoff(self):
        """Event retry should include next_retry_at with exponential backoff."""
        import asyncio

        from selko.services.events import fail_event_sync

        self.pool.rows.append({"sync_attempts": 1, "max_sync_attempts": 3})
        with freeze_retry_clock():
            asyncio.run(fail_event_sync(self.pool, "event-1", "Calendar API error"))

        sql, args = self.pool.calls[-1]
        assert args[0] == "approved"
        assert args[2] == FROZEN_NOW + timedelta(seconds=60)

    def test_event_delay_capped(self):
        """Event delay should also be capped at 3600s."""
        import asyncio

        from selko.services.events import fail_event_sync

        self.pool.rows.append({"sync_attempts": 7, "max_sync_attempts": 10})
        with freeze_retry_clock():
            asyncio.run(fail_event_sync(self.pool, "event-1", "error"))

        sql, args = self.pool.calls[-1]
        assert args[2] == FROZEN_NOW + timedelta(seconds=3600)

    def test_calendar_quota_deferral_releases_claim_without_spending_attempt(self):
        """Quota deferral returns the claimed event to its pre-claim budget."""
        import asyncio

        from selko.services.events import defer_event_sync_for_quota

        reset_at = "2026-04-10T00:00:00+00:00"

        asyncio.run(defer_event_sync_for_quota(self.pool, "event-1", 2, reset_at))

        sql, args = self.pool.calls[-1]
        assert "CASE WHEN calendar_sync_action = 'cancel' THEN 'cancel_queued' ELSE 'approved' END" in sql
        assert "sync_attempts = $1" in sql
        assert args[0] == 1
        assert "Daily calendar sync quota exceeded" in sql
        assert args[1] == reset_at

    def test_oauth_park_releases_claim_without_spending_attempt_or_dead_lettering(self):
        """An OAuth-blocked sync isn't a real attempt: no dead-letter, no backoff.

        docs/specs/oauth-reconnect-catch-up.md item 1: expired/insufficient
        OAuth "does not consume further automatic attempts" and must clear
        any stale retry/dead-letter state so the event is a clean `approved`
        row once the user reauthorizes.
        """
        import asyncio

        from selko.services.events import park_event_for_oauth_reauth

        asyncio.run(park_event_for_oauth_reauth(
            self.pool,
            "event-1",
            2,
            "oauth_required",
            "Google Calendar needs to be reconnected.",
        ))

        sql, args = self.pool.calls[-1]
        assert "CASE WHEN calendar_sync_action = 'cancel' THEN 'cancel_queued' ELSE 'approved' END" in sql
        assert "sync_attempts = $1" in sql
        assert args[0] == 1
        assert args[1] == "Google Calendar needs to be reconnected."
        assert args[2] == "oauth_required"
        assert "dead_letter_at = NULL" in sql


# ===========================================================================
# Dead Letter Pattern Tests
# ===========================================================================


class TestDeadLetterEmail:
    @pytest.fixture(autouse=True)
    def pool(self, fake_pg_pool):
        self.pool = fake_pg_pool

    """Tests for dead letter fields when max attempts exceeded for emails."""

    def test_dead_letter_on_max_attempts(self):
        """When max attempts exceeded, dead_letter fields should be set."""
        import asyncio

        from selko.services.emails import fail_email_processing

        self.pool.rows.append({"attempts": 3, "max_attempts": 3})
        asyncio.run(fail_email_processing(self.pool, "email-1", "Permanent failure"))

        sql, args = self.pool.calls[-1]
        assert "processing_status = 'failed'" in sql
        assert "dead_letter_reason = $2" in sql
        assert "dead_letter_at = $3" in sql
        # Should NOT have next_retry_at
        assert "next_retry_at" not in sql

    def test_no_dead_letter_on_retry(self):
        """When retries remain, dead_letter fields should NOT be set."""
        import asyncio

        from selko.services.emails import fail_email_processing

        self.pool.rows.append({"attempts": 1, "max_attempts": 3})
        asyncio.run(fail_email_processing(self.pool, "email-1", "Transient failure"))

        sql, args = self.pool.calls[-1]
        assert "processing_status = 'pending'" in sql
        assert "dead_letter_reason" not in sql
        assert "dead_letter_at" not in sql


class TestDeadLetterEvent:
    @pytest.fixture(autouse=True)
    def pool(self, fake_pg_pool):
        self.pool = fake_pg_pool

    """Tests for dead letter fields when max attempts exceeded for events."""

    def test_dead_letter_on_max_sync_attempts(self):
        """When max sync attempts exceeded, dead_letter fields should be set."""
        import asyncio

        from selko.services.events import fail_event_sync

        self.pool.rows.append({"sync_attempts": 3, "max_sync_attempts": 3})
        asyncio.run(fail_event_sync(self.pool, "event-1", "Calendar API down"))

        sql, args = self.pool.calls[-1]
        assert "status = 'sync_failed'" in sql
        assert "dead_letter_reason = $2" in sql
        assert "dead_letter_at = $3" in sql

    def test_no_dead_letter_on_event_retry(self):
        """When retries remain, dead_letter fields should NOT be set."""
        import asyncio

        from selko.services.events import fail_event_sync

        self.pool.rows.append({"sync_attempts": 1, "max_sync_attempts": 3})
        asyncio.run(fail_event_sync(self.pool, "event-1", "Temporary error"))

        sql, args = self.pool.calls[-1]
        assert args[0] == "approved"
        assert "dead_letter_reason" not in sql


# ===========================================================================
# Circuit Breaker Tests
# ===========================================================================


class TestCircuitBreakerStateTransitions:
    """Tests for circuit breaker state machine (closed -> open -> half-open -> closed)."""

    def test_starts_closed(self):
        """New circuit breaker should be in CLOSED state."""
        cb = CircuitBreaker(min_calls=3)
        assert cb.get_state("test") == CircuitState.CLOSED
        assert cb.is_available("test") is True

    def test_stays_closed_below_threshold(self):
        """Circuit stays CLOSED when failure rate is below threshold."""
        cb = CircuitBreaker(failure_threshold=0.5, min_calls=5)
        # 4 successes, 1 failure = 20% failure rate
        for _ in range(4):
            cb.record_success("test")
        cb.record_failure("test")

        assert cb.get_state("test") == CircuitState.CLOSED
        assert cb.is_available("test") is True

    def test_opens_on_high_failure_rate(self):
        """Circuit OPENS when failure rate exceeds threshold."""
        cb = CircuitBreaker(failure_threshold=0.5, min_calls=4)
        # 2 successes, 3 failures = 60% failure rate
        cb.record_success("test")
        cb.record_success("test")
        cb.record_failure("test")
        cb.record_failure("test")
        cb.record_failure("test")

        assert cb.get_state("test") == CircuitState.OPEN
        assert cb.is_available("test") is False

    def test_stays_closed_below_min_calls(self):
        """Circuit stays CLOSED when total calls below min_calls."""
        cb = CircuitBreaker(failure_threshold=0.5, min_calls=10)
        # All failures but below min_calls threshold
        for _ in range(9):
            cb.record_failure("test")

        assert cb.get_state("test") == CircuitState.CLOSED

    def test_transitions_to_half_open_after_cooldown(self):
        """After cooldown, OPEN circuit should transition to HALF_OPEN."""
        clock = FakeClock()
        cb = CircuitBreaker(
            failure_threshold=0.5,
            min_calls=3,
            cooldown_seconds=0.1,  # Very short for testing
            clock=clock,
        )
        # Open the circuit
        for _ in range(3):
            cb.record_failure("test")

        assert cb.get_state("test") == CircuitState.OPEN
        assert cb.is_available("test") is False

        clock.advance(0.15)

        # Should now be half-open
        assert cb.is_available("test") is True
        assert cb.get_state("test") == CircuitState.HALF_OPEN

    def test_half_open_closes_on_success(self):
        """HALF_OPEN circuit should CLOSE on success."""
        clock = FakeClock()
        cb = CircuitBreaker(
            failure_threshold=0.5,
            min_calls=3,
            cooldown_seconds=0.1,
            clock=clock,
        )
        # Open the circuit
        for _ in range(3):
            cb.record_failure("test")

        clock.advance(0.15)
        cb.is_available("test")  # Trigger transition to HALF_OPEN

        # Record success
        cb.record_success("test")
        assert cb.get_state("test") == CircuitState.CLOSED

    def test_half_open_reopens_on_failure(self):
        """HALF_OPEN circuit should re-OPEN on failure."""
        clock = FakeClock()
        cb = CircuitBreaker(
            failure_threshold=0.5,
            min_calls=3,
            cooldown_seconds=0.1,
            clock=clock,
        )
        # Open the circuit
        for _ in range(3):
            cb.record_failure("test")

        clock.advance(0.15)
        cb.is_available("test")  # Trigger transition to HALF_OPEN

        # Record failure - should check threshold and re-open
        cb.record_failure("test")
        # The state depends on whether the threshold check re-opens it
        # Since we already have accumulated failures, adding another pushes it over
        assert cb.get_state("test") == CircuitState.OPEN


class TestCircuitBreakerSeparateServices:
    """Tests that circuit breaker tracks services independently."""

    def test_separate_services_independent(self):
        """Failures in one service should not affect another."""
        cb = CircuitBreaker(failure_threshold=0.5, min_calls=3)

        # Fail "gmail" service
        for _ in range(5):
            cb.record_failure("gmail")

        # "google_calendar" should still be available
        assert cb.is_available("gmail") is False
        assert cb.is_available("google_calendar") is True

    def test_separate_services_independent_success(self):
        """Success in one service does not reset another."""
        cb = CircuitBreaker(failure_threshold=0.5, min_calls=3)

        # Fail both services
        for _ in range(5):
            cb.record_failure("gmail")
            cb.record_failure("llm")

        assert cb.is_available("gmail") is False
        assert cb.is_available("llm") is False

        # Recording success on gmail (in half_open) should not affect llm
        # For this test, manually set gmail to half_open
        cb._state["gmail"] = CircuitState.HALF_OPEN
        cb.record_success("gmail")

        assert cb.get_state("gmail") == CircuitState.CLOSED
        assert cb.get_state("llm") == CircuitState.OPEN

    def test_three_independent_services(self):
        """Three services (gmail, google_calendar, llm) tracked independently."""
        cb = CircuitBreaker(failure_threshold=0.5, min_calls=3)

        # All start available
        assert cb.is_available("gmail") is True
        assert cb.is_available("google_calendar") is True
        assert cb.is_available("llm") is True

        # Fail only gmail
        for _ in range(3):
            cb.record_failure("gmail")

        assert cb.is_available("gmail") is False
        assert cb.is_available("google_calendar") is True
        assert cb.is_available("llm") is True


class TestCircuitBreakerWindowCleanup:
    """Tests for time-window based cleanup of old entries."""

    def test_old_entries_cleaned(self):
        """Entries older than window_seconds should be cleaned up."""
        clock = FakeClock()
        cb = CircuitBreaker(
            failure_threshold=0.5,
            min_calls=3,
            window_seconds=0.1,  # Very short window
            clock=clock,
        )

        # Record failures (should open circuit)
        for _ in range(5):
            cb.record_failure("test")
        assert cb.get_state("test") == CircuitState.OPEN

        clock.advance(0.15)

        # After cleanup, old failures should be gone
        # The circuit is still OPEN but is_available checks cooldown
        # New calls with successes should eventually close it
        cb._state["test"] = CircuitState.CLOSED  # Reset for this test
        cb._clean_old_entries("test")
        assert len(cb._calls["test"]) == 0
