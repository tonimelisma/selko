"""Acceptance tests for the C3 cancellation state machine, on a real SQLite database.

The queue transitions are `selko.db.calendar_work`; the provider write is the
real calendar worker (`workers.calendar_sync`) with Google's API mocked.
"""

from unittest.mock import MagicMock, patch

import pytest

from selko.db import calendar_work, errors
from selko.workers import calendar_sync


def _claimed_event(item, event):
    """The event dict the worker pool hands the calendar worker after a claim."""
    return {
        **event,
        "calendar_work_desired_event": item["desired_event"],
        "expected_provider_revision": item["expected_provider_revision"],
        "force_overwrite": item["force_overwrite"],
        "calendar_work_item_provider": item["provider"],
    }


@pytest.mark.integration
class TestAutomaticCancellation:
    @pytest.fixture
    def user_id(self, factory):
        user_id = factory.user()
        factory.integration(user_id, provider="google_calendar", access_token="c3-test-token")
        return user_id

    async def test_cancel_claim_and_completion_are_worker_owned(self, db, factory, user_id):
        event_id = factory.event(
            user_id,
            review_status="active",
            title="Original title",
            start_datetime="2026-09-01T14:00:00.000000Z",
            end_datetime="2026-09-01T15:00:00.000000Z",
            google_calendar_event_id="google-c3-event",
        )

        queued = calendar_work.queue_event_cancellation(db, user_id, event_id)
        assert queued["status"] == "cancel_queued"
        work_item = factory.row("calendar_work_items", queued["work_item_id"])
        assert (work_item["status"], work_item["action"], work_item["generation"]) == (
            "pending", "cancel", 1,
        )

        claimed = calendar_work.claim_calendar_work_item(db, "c3-worker")
        assert claimed is not None
        item, event = claimed
        assert event["id"] == event_id
        assert factory.row("calendar_work_items", item["id"])["status"] == "processing"
        assert item["action"] == "cancel"

        with patch("selko.services.calendars.get_credentials", return_value=MagicMock()), \
                patch("selko.services.calendars.build") as build:
            service = build.return_value
            service.events.return_value.get.return_value.execute.return_value = {
                "id": "google-c3-event", "summary": "Original title",
            }
            await calendar_sync.cancel_event(db, MagicMock(), _claimed_event(item, event))
        body = service.events.return_value.update.call_args.kwargs["body"]
        assert body["summary"] == "CANCELLED: Original title"

        completed = calendar_work.complete_calendar_work(
            db, item["id"], "c3-worker", item["generation"], None
        )
        assert completed is True
        final = factory.row("events", event_id)
        assert (final["review_status"], final["title"], final["google_calendar_event_id"]) == (
            "cancelled", "Original title", None,
        )

    async def test_stale_upsert_completion_cannot_reset_cancellation(self, db, factory, user_id):
        event_id = factory.event(
            user_id,
            review_status="active",
            title="Race event",
            start_datetime="2026-09-02T14:00:00.000000Z",
            google_calendar_event_id="google-race-event",
        )
        calendar_work.enqueue_calendar_work(db, user_id, event_id, "upsert", {"title": "Race event"})
        claimed = calendar_work.claim_calendar_work_item(db, "upsert-worker")
        assert claimed is not None
        old_item, _ = claimed

        # Superseding an actively leased item is the authoritative race
        # transition; the user-facing cancellation refuses a syncing event
        # rather than mutating it underneath its worker.
        with pytest.raises(errors.InvalidArgument):
            calendar_work.queue_event_cancellation(db, user_id, event_id)
        calendar_work.enqueue_calendar_work(db, user_id, event_id, "cancel", None)

        completed = calendar_work.complete_calendar_work(
            db, old_item["id"], "upsert-worker", old_item["generation"], "google-race-event"
        )
        assert completed is False
        assert factory.row("events", event_id)["review_status"] == "active"
        latest = db.query_one(
            "SELECT status, action FROM calendar_work_items WHERE event_id = ? "
            "ORDER BY generation DESC LIMIT 1",
            (event_id,),
        )
        assert (latest["status"], latest["action"]) == ("pending", "cancel")
