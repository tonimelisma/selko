"""Integration tests for the calendar recovery worker, on a real SQLite database.

Covers docs/specs/oauth-reconnect-catch-up.md section 3 (Calendar) regression
coverage: only oauth_required/oauth_scope_required blocked events get tagged,
quota/validation/permission/unknown failures are left untouched, and progress
finalizes once every tagged event reaches a terminal state.

The tagging and progress steps run through the worker's service wrappers
(`services.calendars`); the claim and the reauthorization are
`selko.db.recovery`, and the calendar delivery in between is the real
`selko.db.calendar_work` lease.
"""

import pytest

from selko.db import calendar_work
from selko.db import recovery as db_recovery
from selko.services.calendars import (
    refresh_waiting_calendar_recoveries,
    requeue_calendar_recovery_batch,
)


@pytest.fixture
def user_id(factory):
    return factory.user()


def _make_blocked_event(db, factory, user_id, failure_code="oauth_required"):
    event_id = factory.event(
        user_id,
        review_status="active",
        title="Recovery worker test event",
        start_datetime="2026-05-01T14:00:00.000000Z",
    )
    calendar_work.enqueue_calendar_work(
        db, user_id, event_id, "upsert", {"title": "Recovery worker test event"}
    )
    if failure_code is not None:
        with db.write() as tx:
            tx.execute(
                "UPDATE calendar_work_items SET failure_code = ?, status = 'failed' WHERE event_id = ?",
                (failure_code, event_id),
            )
    return event_id


def _create_and_claim_recovery(db, user_id):
    db_recovery.complete_integration_reauthorization(
        db,
        user_id,
        "google_calendar",
        access_token="access-1",
        refresh_token="refresh-1",
        token_expiry=None,
        scopes=["calendar"],
        provider_email=None,
    )
    return db_recovery.claim_integration_recovery(db, "worker-1", lock_seconds=120)


def _recovery(db, recovery_id):
    return db.schema.decode(
        "integration_recoveries",
        db.query_one("SELECT * FROM integration_recoveries WHERE id = ?", (recovery_id,)),
    )


@pytest.mark.integration
class TestRequeueCalendarRecoveryBatch:
    async def test_tags_only_oauth_blocked_approved_events(self, db, factory, user_id):
        oauth_event_id = _make_blocked_event(db, factory, user_id, "oauth_required")
        scope_event_id = _make_blocked_event(db, factory, user_id, "oauth_scope_required")
        untouched_event_id = _make_blocked_event(db, factory, user_id, "permission_denied")
        no_code_event_id = _make_blocked_event(db, factory, user_id, None)

        recovery = _create_and_claim_recovery(db, user_id)
        tagged = await requeue_calendar_recovery_batch(db, recovery["id"], "worker-1")
        assert tagged == 2

        tagged_ids = {
            row["id"]
            for row in db.query("SELECT id FROM events WHERE recovery_id = ?", (recovery["id"],))
        }
        assert tagged_ids == {oauth_event_id, scope_event_id}
        assert untouched_event_id not in tagged_ids
        assert no_code_event_id not in tagged_ids

    async def test_returns_negative_one_when_claim_lost(self, db, user_id):
        recovery = _create_and_claim_recovery(db, user_id)

        result = await requeue_calendar_recovery_batch(db, recovery["id"], "a-different-worker")

        assert result == -1

    async def test_reclaims_processing_recovery_with_expired_lock(self, db, user_id):
        """A crashed worker's claim (processing + expired lock) must be reclaimed
        on the next claim instead of waiting for an API restart (#239 was startup
        only; the claim itself must self-heal)."""
        recovery = _create_and_claim_recovery(db, user_id)
        with db.write() as tx:
            tx.execute(
                "UPDATE integration_recoveries SET locked_until = ? WHERE id = ?",
                ("2020-01-01T00:00:00.000000Z", recovery["id"]),
            )

        reclaimed = db_recovery.claim_integration_recovery(db, "worker-2", lock_seconds=120)

        assert reclaimed is not None
        assert reclaimed["id"] == recovery["id"]
        assert reclaimed["status"] == "processing"
        assert reclaimed["locked_by"] == "worker-2"
        assert reclaimed["attempts"] == 2

    async def test_finalizes_completed_once_tagged_events_synced(self, db, factory, user_id):
        event_id = _make_blocked_event(db, factory, user_id)
        recovery = _create_and_claim_recovery(db, user_id)
        await requeue_calendar_recovery_batch(db, recovery["id"], "worker-1")

        # The normal calendar worker picks the revived item up and delivers it.
        claimed = calendar_work.claim_calendar_work_item(db, "calendar-worker")
        assert claimed is not None
        item, event = claimed
        assert event["id"] == event_id
        assert calendar_work.complete_calendar_work(
            db, item["id"], "calendar-worker", item["generation"], "recovered-google-event"
        ) is True

        assert await refresh_waiting_calendar_recoveries(db) == 1

        row = _recovery(db, recovery["id"])
        assert row["status"] == "completed"
        assert row["completed_count"] == 1
        assert row["remaining_count"] == 0

    async def test_finalizes_completed_with_errors_when_a_tagged_event_fails(self, db, factory, user_id):
        event_id = _make_blocked_event(db, factory, user_id)
        recovery = _create_and_claim_recovery(db, user_id)
        await requeue_calendar_recovery_batch(db, recovery["id"], "worker-1")

        # The calendar worker fails the event permanently for a non-OAuth reason.
        item, event = calendar_work.claim_calendar_work_item(db, "calendar-worker")
        assert event["id"] == event_id
        assert calendar_work.fail_calendar_work(
            db, item["id"], "calendar-worker", item["generation"], "invalid_event", retryable=False
        ) == {"fenced": False, "status": "blocked"}

        await refresh_waiting_calendar_recoveries(db)

        assert _recovery(db, recovery["id"])["status"] == "completed_with_errors"

    async def test_still_waiting_while_tagged_event_is_unresolved(self, db, factory, user_id):
        _make_blocked_event(db, factory, user_id)
        recovery = _create_and_claim_recovery(db, user_id)
        await requeue_calendar_recovery_batch(db, recovery["id"], "worker-1")
        await refresh_waiting_calendar_recoveries(db)

        row = _recovery(db, recovery["id"])
        assert row["status"] == "waiting"
        assert row["remaining_count"] == 1
