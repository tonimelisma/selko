"""Unit tests for reliability improvements.

Tests exponential backoff, circuit breaker, dead-letter pattern,
and timeout handling.
"""

from datetime import datetime, timezone


from selko.services.circuit_breaker import CircuitBreaker, CircuitState

FROZEN_NOW = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    """Simple monotonic clock for circuit-breaker tests."""

    def __init__(self, start: float = 0.0):
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


# ===========================================================================
# Exponential Backoff Tests
# ===========================================================================


class TestFencedFailEmailProcessing:
    """S1: exponential backoff and dead-lettering happen inside
    `selko.db.emails.fail_email_processing`; this Python wrapper calls it
    and interprets the outcome. Exercised against a real temporary database.
    """

    @staticmethod
    def _claimed(db, factory, *, max_attempts: int = 3) -> dict:
        from selko.db import emails as db_emails

        factory.email(factory.user(), max_attempts=max_attempts)
        email = db_emails.claim_unprocessed_email(db, "worker-a", 300)
        assert email is not None
        return email

    def test_passes_worker_and_generation_to_the_fence(self, db, factory):
        import asyncio

        from selko.services.emails import fail_email_processing

        email = self._claimed(db, factory)
        outcome = asyncio.run(fail_email_processing(
            db, email["id"], "worker-a", email["lock_generation"], "test error", 60, 1800,
        ))

        assert outcome["fenced"] is False
        row = factory.row("emails", email["id"])
        assert (row["processing_status"], row["processing_error"], row["locked_by"]) == ("pending", "test error", None)

    def test_pending_outcome_is_returned(self, db, factory):
        import asyncio

        from selko.services.emails import fail_email_processing

        email = self._claimed(db, factory)
        outcome = asyncio.run(fail_email_processing(
            db, email["id"], "worker-a", email["lock_generation"], "transient", 60, 1800,
        ))

        assert outcome["status"] == "pending"
        assert outcome["attempts"] == 1
        assert outcome["next_retry_at"] is not None

    def test_terminal_outcome_is_returned(self, db, factory):
        import asyncio

        from selko.services.emails import fail_email_processing

        email = self._claimed(db, factory, max_attempts=1)
        outcome = asyncio.run(fail_email_processing(
            db, email["id"], "worker-a", email["lock_generation"], "permanent", 60, 1800,
        ))

        assert outcome["status"] == "failed"
        assert factory.row("emails", email["id"])["dead_letter_reason"] == "permanent"

    def test_fenced_outcome_is_returned_without_raising(self, db, factory):
        """A stale (worker, generation) must not raise — a replacement worker
        already owns the row."""
        import asyncio

        from selko.services.emails import fail_email_processing

        email = self._claimed(db, factory)
        outcome = asyncio.run(fail_email_processing(
            db, email["id"], "stale-worker", email["lock_generation"], "too late", 60, 1800,
        ))

        assert outcome["fenced"] is True
        assert factory.row("emails", email["id"])["locked_by"] == "worker-a"


def _processing_item(factory, *, attempts=1, max_attempts=3):
    """A calendar work item leased to worker-1 at generation 2, on a real database."""
    from selko.db.codec import new_id

    user = factory.user()
    event = factory.event(user, review_status="active")
    item = factory._insert("calendar_work_items", {
        "id": new_id(), "event_id": event, "user_id": user, "action": "upsert", "generation": 2,
        "status": "processing", "desired_event": {"title": "Event"}, "attempts": attempts,
        "max_attempts": max_attempts, "locked_by": "worker-1",
        "locked_until": "2099-01-01T00:00:00.000000Z", "provider": "google_calendar",
    })
    return item


def _item(factory, item_id):
    return factory.row("calendar_work_items", item_id)


class TestExponentialBackoffEvents:
    """The Python boundary around the fenced calendar work transitions, on a real database."""

    def test_event_retry_with_backoff(self, db, factory):
        """A retryable failure goes back to pending with a backoff, keeping the attempt."""
        import asyncio

        from selko.services.events import WorkItemLease, fail_event_sync

        item_id = _processing_item(factory, attempts=1)
        asyncio.run(fail_event_sync(db, WorkItemLease(item_id, "worker-1", 2), "Calendar API error"))

        row = _item(factory, item_id)
        assert (row["status"], row["failure_code"], row["failure_detail"]) == (
            "pending", "calendar_sync_failed", "Calendar API error",
        )
        assert row["locked_by"] is None and row["next_retry_at"] is not None
        assert row["attempts"] == 1

    def test_event_delay_capped(self, db, factory):
        """The backoff never exceeds the 30-minute cap, however many attempts."""
        import asyncio
        from datetime import datetime

        from selko.db.calendar_work import retry_delay_seconds
        from selko.services.events import WorkItemLease, fail_event_sync

        assert retry_delay_seconds(20) == 1800
        item_id = _processing_item(factory, attempts=2, max_attempts=50)
        asyncio.run(fail_event_sync(db, WorkItemLease(item_id, "worker-1", 2), "error"))

        row = _item(factory, item_id)
        delay = (datetime.fromisoformat(row["next_retry_at"]) - datetime.fromisoformat(row["updated_at"]))
        assert delay.total_seconds() == retry_delay_seconds(2) <= 1800

    def test_calendar_quota_deferral_releases_claim_without_spending_attempt(self, db, factory):
        """Quota deferral returns the claimed event to its pre-claim budget."""
        import asyncio

        from selko.services.events import WorkItemLease, defer_event_sync_for_quota

        reset_at = "2026-04-10T00:00:00+00:00"
        item_id = _processing_item(factory, attempts=1)
        asyncio.run(defer_event_sync_for_quota(db, WorkItemLease(item_id, "worker-1", 2), reset_at))

        row = _item(factory, item_id)
        assert (row["status"], row["attempts"], row["locked_by"]) == ("pending", 0, None)
        assert row["next_retry_at"] == "2026-04-10T00:00:00.000000Z"
        assert row["failure_detail"] == "Daily calendar sync quota exceeded"

    def test_oauth_park_releases_claim_without_spending_attempt_or_dead_lettering(self, db, factory):
        """An OAuth-blocked sync isn't a real attempt: no dead-letter, no backoff.

        docs/specs/oauth-reconnect-catch-up.md item 1: expired/insufficient
        OAuth "does not consume further automatic attempts"; the item is parked
        (blocked, with the OAuth failure code) until the user reauthorizes and
        recovery requeues it.
        """
        import asyncio

        from selko.services.events import WorkItemLease, park_event_for_oauth_reauth

        item_id = _processing_item(factory, attempts=1)
        asyncio.run(park_event_for_oauth_reauth(
            db, WorkItemLease(item_id, "worker-1", 2), "oauth_required",
            "Google Calendar needs to be reconnected.",
        ))

        row = _item(factory, item_id)
        assert (row["status"], row["failure_code"]) == ("blocked", "oauth_required")
        assert row["next_retry_at"] is None, "no backoff for an OAuth block"
        assert row["locked_by"] is None

    def test_a_stale_lease_changes_nothing(self, db, factory):
        import asyncio

        from selko.services.events import WorkItemLease, fail_event_sync

        item_id = _processing_item(factory)
        asyncio.run(fail_event_sync(db, WorkItemLease(item_id, "worker-1", 1), "late"))

        assert _item(factory, item_id)["status"] == "processing"


# ===========================================================================
# Dead Letter Pattern Tests
# ===========================================================================


class TestDeadLetterEmail:
    """S1: dead-letter vs retry is now decided inside the SQL RPC (see
    ``TestFencedFailEmailProcessing``); real dead-lettering-at-limit coverage
    lives in ``test_integration_email_state_machine.py``."""


class TestDeadLetterEvent:
    """A calendar work item that spends its budget ends failed; one with budget left retries."""

    def test_dead_letter_on_max_sync_attempts(self, db, factory):
        import asyncio

        from selko.services.events import WorkItemLease, fail_event_sync

        item_id = _processing_item(factory, attempts=3, max_attempts=3)
        asyncio.run(fail_event_sync(db, WorkItemLease(item_id, "worker-1", 2), "Calendar API down"))

        row = _item(factory, item_id)
        assert (row["status"], row["failure_detail"]) == ("failed", "Calendar API down")
        assert row["completed_at"] is not None and row["next_retry_at"] is None

    def test_no_dead_letter_on_event_retry(self, db, factory):
        import asyncio

        from selko.services.events import WorkItemLease, fail_event_sync

        item_id = _processing_item(factory, attempts=1, max_attempts=3)
        asyncio.run(fail_event_sync(db, WorkItemLease(item_id, "worker-1", 2), "Temporary error"))

        row = _item(factory, item_id)
        assert row["status"] == "pending"
        assert row["completed_at"] is None


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
