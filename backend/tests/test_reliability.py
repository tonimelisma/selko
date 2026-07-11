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


class TestExponentialBackoff:
    """Tests for exponential backoff calculation in fail_email_processing."""

    def _make_mock_client(self, attempts: int, max_attempts: int):
        """Create a mock client that returns given attempt counts."""
        client = MagicMock()
        select_result = MagicMock()
        select_result.data = {
            "attempts": attempts,
            "max_attempts": max_attempts,
        }
        client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = select_result
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        return client

    def test_first_retry_delay_60s(self):
        """First retry (attempt 1) should have 60s delay."""
        from selko.services.emails import fail_email_processing

        client = self._make_mock_client(attempts=1, max_attempts=3)
        with freeze_retry_clock():
            fail_email_processing(client, "email-1", "test error")

        # Check the update call includes next_retry_at
        update_call = client.table.return_value.update.call_args[0][0]
        assert update_call["processing_status"] == "pending"
        assert "next_retry_at" in update_call
        retry_at = datetime.fromisoformat(update_call["next_retry_at"])
        assert retry_at == FROZEN_NOW + timedelta(seconds=60)

    def test_second_retry_delay_120s(self):
        """Second retry (attempt 2) should have 120s delay."""
        from selko.services.emails import fail_email_processing

        client = self._make_mock_client(attempts=2, max_attempts=3)
        with freeze_retry_clock():
            fail_email_processing(client, "email-1", "test error")

        update_call = client.table.return_value.update.call_args[0][0]
        assert update_call["processing_status"] == "pending"
        retry_at = datetime.fromisoformat(update_call["next_retry_at"])
        assert retry_at == FROZEN_NOW + timedelta(seconds=120)

    def test_delay_capped_at_3600s(self):
        """Delay should be capped at 3600s (1 hour) for high attempt counts."""
        from selko.services.emails import fail_email_processing

        # Attempt 7 would be 60 * 2^6 = 3840, but should be capped at 3600
        client = self._make_mock_client(attempts=7, max_attempts=10)
        with freeze_retry_clock():
            fail_email_processing(client, "email-1", "test error")

        update_call = client.table.return_value.update.call_args[0][0]
        retry_at = datetime.fromisoformat(update_call["next_retry_at"])
        assert retry_at == FROZEN_NOW + timedelta(seconds=3600)

    def test_backoff_doubles_each_attempt(self):
        """Verify delay doubles exactly with each attempt until the cap."""
        from selko.services.emails import fail_email_processing

        delays = []
        for attempt in [1, 2, 3, 4]:
            client = self._make_mock_client(attempts=attempt, max_attempts=5)
            with freeze_retry_clock():
                fail_email_processing(client, f"email-{attempt}", "test error")
            update_call = client.table.return_value.update.call_args[0][0]
            retry_at = datetime.fromisoformat(update_call["next_retry_at"])
            delays.append(int((retry_at - FROZEN_NOW).total_seconds()))

        assert delays == [60, 120, 240, 480]


class TestExponentialBackoffEvents:
    """Tests for exponential backoff in fail_event_sync."""

    def _make_mock_client(self, sync_attempts: int, max_sync_attempts: int):
        """Create a mock client that returns given attempt counts."""
        client = MagicMock()
        select_result = MagicMock()
        select_result.data = {
            "sync_attempts": sync_attempts,
            "max_sync_attempts": max_sync_attempts,
        }
        client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = select_result
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        return client

    def test_event_retry_with_backoff(self):
        """Event retry should include next_retry_at with exponential backoff."""
        from selko.services.events import fail_event_sync

        client = self._make_mock_client(sync_attempts=1, max_sync_attempts=3)
        with freeze_retry_clock():
            fail_event_sync(client, "event-1", "Calendar API error")

        update_call = client.table.return_value.update.call_args[0][0]
        assert update_call["status"] == "approved"
        assert update_call["next_retry_at"] == (FROZEN_NOW + timedelta(seconds=60)).isoformat()

    def test_event_delay_capped(self):
        """Event delay should also be capped at 3600s."""
        from selko.services.events import fail_event_sync

        client = self._make_mock_client(sync_attempts=7, max_sync_attempts=10)
        with freeze_retry_clock():
            fail_event_sync(client, "event-1", "error")

        update_call = client.table.return_value.update.call_args[0][0]
        retry_at = datetime.fromisoformat(update_call["next_retry_at"])
        assert retry_at == FROZEN_NOW + timedelta(seconds=3600)


# ===========================================================================
# Dead Letter Pattern Tests
# ===========================================================================


class TestDeadLetterEmail:
    """Tests for dead letter fields when max attempts exceeded for emails."""

    def _make_mock_client(self, attempts: int, max_attempts: int):
        """Create a mock client that returns given attempt counts."""
        client = MagicMock()
        select_result = MagicMock()
        select_result.data = {
            "attempts": attempts,
            "max_attempts": max_attempts,
        }
        client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = select_result
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        return client

    def test_dead_letter_on_max_attempts(self):
        """When max attempts exceeded, dead_letter fields should be set."""
        from selko.services.emails import fail_email_processing

        client = self._make_mock_client(attempts=3, max_attempts=3)
        fail_email_processing(client, "email-1", "Permanent failure")

        update_call = client.table.return_value.update.call_args[0][0]
        assert update_call["processing_status"] == "failed"
        assert update_call["dead_letter_reason"] == "Permanent failure"
        assert "dead_letter_at" in update_call
        # Should NOT have next_retry_at
        assert "next_retry_at" not in update_call

    def test_no_dead_letter_on_retry(self):
        """When retries remain, dead_letter fields should NOT be set."""
        from selko.services.emails import fail_email_processing

        client = self._make_mock_client(attempts=1, max_attempts=3)
        fail_email_processing(client, "email-1", "Transient failure")

        update_call = client.table.return_value.update.call_args[0][0]
        assert update_call["processing_status"] == "pending"
        assert "dead_letter_reason" not in update_call
        assert "dead_letter_at" not in update_call


class TestDeadLetterEvent:
    """Tests for dead letter fields when max attempts exceeded for events."""

    def _make_mock_client(self, sync_attempts: int, max_sync_attempts: int):
        """Create a mock client that returns given attempt counts."""
        client = MagicMock()
        select_result = MagicMock()
        select_result.data = {
            "sync_attempts": sync_attempts,
            "max_sync_attempts": max_sync_attempts,
        }
        client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = select_result
        client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        return client

    def test_dead_letter_on_max_sync_attempts(self):
        """When max sync attempts exceeded, dead_letter fields should be set."""
        from selko.services.events import fail_event_sync

        client = self._make_mock_client(sync_attempts=3, max_sync_attempts=3)
        fail_event_sync(client, "event-1", "Calendar API down")

        update_call = client.table.return_value.update.call_args[0][0]
        assert update_call["status"] == "sync_failed"
        assert update_call["dead_letter_reason"] == "Calendar API down"
        assert "dead_letter_at" in update_call

    def test_no_dead_letter_on_event_retry(self):
        """When retries remain, dead_letter fields should NOT be set."""
        from selko.services.events import fail_event_sync

        client = self._make_mock_client(sync_attempts=1, max_sync_attempts=3)
        fail_event_sync(client, "event-1", "Temporary error")

        update_call = client.table.return_value.update.call_args[0][0]
        assert update_call["status"] == "approved"
        assert "dead_letter_reason" not in update_call


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
