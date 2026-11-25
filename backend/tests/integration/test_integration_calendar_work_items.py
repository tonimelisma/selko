"""Contracts for the S2 calendar work-item owner, end to end on a real SQLite database.

Queue transitions are `selko.db.calendar_work`; the provider write is the real
calendar worker (`workers.calendar_sync` -> `services.calendars`) with Google's
API mocked. The tests in `tests/db/test_calendar_work.py` cover each
transition in isolation; these run them together with the writer.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from selko.db import calendar_work
from selko.db.codec import to_timestamp
from selko.workers import calendar_sync


pytestmark = [pytest.mark.integration]


def _desired(title: str = "S2 event") -> dict:
    return {
        "title": title,
        "start_datetime": "2026-09-01T14:00:00Z",
        "end_datetime": "2026-09-01T15:00:00Z",
        "all_day": False,
        "location": "Test room",
        "description": "S2 integration probe",
        "importance": "action_required",
        "source_attribution": None,
    }


def _claimed_event(item, event):
    """The event dict the worker pool hands the calendar worker after a claim."""
    return {
        **event,
        "calendar_work_desired_event": item["desired_event"],
        "expected_provider_revision": item["expected_provider_revision"],
        "force_overwrite": item["force_overwrite"],
        "calendar_work_item_provider": item["provider"],
    }


@pytest.fixture
def user_id(factory):
    user_id = factory.user()
    factory.integration(user_id, provider="google_calendar", access_token="s2-test-token")
    return user_id


async def test_enqueue_claim_complete_is_item_fenced(db, factory, user_id):
    event_id = factory.event(
        user_id,
        title="S2 event",
        start_datetime="2026-09-01T14:00:00.000000Z",
        end_datetime="2026-09-01T15:00:00.000000Z",
        # Calendar work is queued for an event the user has approved.
        # Queueing never promotes the event itself -- events.review_status
        # owns the user decision, so the caller states it.
        review_status="active",
    )

    queued = calendar_work.enqueue_calendar_work(db, user_id, event_id, "upsert", _desired())

    claimed = calendar_work.claim_calendar_work_item(db, "s2-worker")
    assert claimed is not None
    item, event = claimed
    assert item["id"] == queued["id"]
    # Delivery state is the work item's, not a second column on events.
    assert item["status"] == "processing"
    assert item["provider"] == "google_calendar"

    with patch("selko.services.calendars.get_credentials", return_value=MagicMock()), \
            patch("selko.services.calendars.build") as build:
        service = build.return_value
        service.events.return_value.list.return_value.execute.return_value = {"items": []}
        service.events.return_value.insert.return_value.execute.return_value = {"id": "google-s2-event"}
        provider_event_id = await calendar_sync.sync_event(db, MagicMock(), _claimed_event(item, event))
    assert provider_event_id == "google-s2-event"

    # A second worker holding no lease cannot complete it.
    assert calendar_work.complete_calendar_work(
        db, item["id"], "other-worker", item["generation"], "google-s2-event"
    ) is False
    assert calendar_work.complete_calendar_work(
        db, item["id"], "s2-worker", item["generation"], provider_event_id
    ) is True
    final = factory.row("events", event_id)
    assert (final["review_status"], final["google_calendar_event_id"]) == ("active", "google-s2-event")
    assert factory.row("calendar_work_items", item["id"])["status"] == "succeeded"
    log = db.query("SELECT action, google_calendar_event_id FROM calendar_sync_log WHERE event_id = ?",
                   (event_id,))
    assert [tuple(r) for r in log] == [("created", "google-s2-event")]


async def test_new_enqueue_supersedes_old_and_stale_completion_is_fenced(db, factory, user_id):
    event_id = factory.event(user_id, title="Race", review_status="pending_review")
    first = calendar_work.enqueue_calendar_work(db, user_id, event_id, "upsert", _desired("first"))
    claimed = calendar_work.claim_calendar_work_item(db, "old-worker")
    assert claimed is not None
    old_item, _ = claimed

    second = calendar_work.enqueue_calendar_work(db, user_id, event_id, "cancel", None)
    assert first["id"] != second["id"]
    assert calendar_work.complete_calendar_work(
        db, old_item["id"], "old-worker", old_item["generation"], "stale-google-event"
    ) is False
    row = factory.row("calendar_work_items", second["id"])
    assert (row["status"], row["action"], row["generation"]) == ("pending", "cancel", 2)
    assert factory.row("calendar_work_items", first["id"])["status"] == "superseded"
    assert factory.row("events", event_id)["google_calendar_event_id"] is None


async def test_expired_processing_item_is_reclaimable(db, factory, user_id):
    event_id = factory.event(user_id, title="Expired", review_status="pending_review")
    queued = calendar_work.enqueue_calendar_work(db, user_id, event_id, "upsert", _desired("expired"))
    claimed = calendar_work.claim_calendar_work_item(db, "crashed-worker", 1)
    assert claimed is not None
    with db.write() as tx:
        tx.execute(
            "UPDATE calendar_work_items SET locked_until = ? WHERE id = ?",
            (to_timestamp(datetime.now(timezone.utc) - timedelta(seconds=1)), queued["id"]),
        )
    reclaimed = calendar_work.claim_calendar_work_item(db, "reclaimer", 60)
    assert reclaimed is not None
    assert reclaimed[0]["id"] == queued["id"]
    assert factory.row("calendar_work_items", queued["id"])["locked_by"] == "reclaimer"
    # The crashed worker's lease is dead: its completion is fenced.
    assert calendar_work.complete_calendar_work(
        db, queued["id"], "crashed-worker", claimed[0]["generation"], "g"
    ) is False


