"""undo_history_event's calendar side effects, on a real database.

The provider read (`calendars.get_calendar_event`) and the divergence check
(`calendars.assert_calendar_not_diverged`, a provider read) are mocked; the
proposal reopen and the undo enqueue are the real data-layer transitions.
"""

from unittest.mock import patch

import pytest

from selko.db.codec import new_id
from selko.services.calendars import CalendarDivergedError
from selko.services.events import EventsError, undo_history_event

SNAPSHOT = {
    "title": "Old Title",
    "start_datetime": "2026-09-13T10:00:00-07:00",
    "end_datetime": "2026-09-13T14:00:00-07:00",
    "all_day": False,
    "location": "Lot A",
    "description": "Old",
    "importance": "action_required",
}


def _event(factory, user, **overrides):
    values = {
        "title": "Bike Fest",
        "google_calendar_event_id": "gcal-abc",
        "synced_at": "2026-07-12T01:00:00.000000Z",
        "start_datetime": "2026-09-13T17:00:00.000000Z",
        "end_datetime": "2026-09-13T21:00:00.000000Z",
        "all_day": False,
        "location": "Park",
        "description": "Fun",
        "importance": "action_required",
    }
    values.update(overrides)
    return factory.event(user, review_status=values.pop("review_status", "active"), **values)


def _applied_change(factory, user, event, snapshot=SNAPSHOT):
    source = factory.event_source(event, factory.email(user), source_type="update")
    return factory._insert("event_change_proposals", {
        "id": new_id(), "event_id": event, "user_id": user, "source_id": source,
        "kind": "material_update", "status": "applied",
        "change_set": {"kind": "material_update",
                       "changes": [{"field": "title", "before": "Old Title", "after": "New Title"}]},
        "event_snapshot_before": snapshot, "resolution_reason": "user_applied",
        "resolved_at": "2026-07-12T02:00:00.000000Z",
    })


def _work(db, event):
    return [db.schema.decode("calendar_work_items", r) for r in db.query(
        "SELECT * FROM calendar_work_items WHERE event_id = ? ORDER BY generation", (event,))]


def _undo(db, event, user, *, force=False, live=None, diverged=None):
    with patch("selko.services.events.calendars.assert_calendar_not_diverged",
               side_effect=diverged) as check, \
         patch("selko.services.events.calendars.get_calendar_event", return_value=live):
        status = undo_history_event(db, event, user, force=force)
    return status, check


class TestUndoHistoryEventCalendar:
    # Validates: SEL-237
    def test_new_synced_queues_calendar_delete(self, db, factory):
        user = factory.user()
        event = _event(factory, user)

        status, check = _undo(db, event, user, live={"etag": "v1"})

        assert status == "pending_review"
        check.assert_called_once()
        (item,) = _work(db, event)
        assert (item["action"], item["status"]) == ("cancel", "pending")
        assert item["expected_provider_revision"] == "v1"
        assert item["force_overwrite"] is False
        assert factory.row("events", event)["review_status"] == "pending_review"

    # Validates: SEL-238
    def test_diverged_without_force_raises(self, db, factory):
        user = factory.user()
        event = _event(factory, user)

        with pytest.raises(CalendarDivergedError):
            _undo(db, event, user, live={"etag": "v1"},
                  diverged=CalendarDivergedError("edited", ["title"]))

        assert _work(db, event) == [], "nothing is queued for a diverged event"
        assert factory.row("events", event)["review_status"] == "active"

    def test_diverged_with_force_queues_delete(self, db, factory):
        user = factory.user()
        event = _event(factory, user)

        status, check = _undo(db, event, user, force=True, live={"etag": "v1"})

        assert status == "pending_review"
        check.assert_not_called()
        (item,) = _work(db, event)
        assert item["action"] == "cancel"
        assert item["force_overwrite"] is True

    # Validates: SEL-236
    def test_applied_change_restores_calendar(self, db, factory):
        user = factory.user()
        event = _event(factory, user, title="New Title")
        proposal = _applied_change(factory, user, event)

        status, _ = _undo(db, event, user, live={"id": "gcal-abc", "etag": "v1"})

        assert status == "active"
        assert factory.row("event_change_proposals", proposal)["status"] == "pending"
        row = factory.row("events", event)
        assert (row["title"], row["location"], row["review_status"]) == ("Old Title", "Lot A", "active")
        (item,) = _work(db, event)
        assert item["action"] == "upsert"
        assert item["desired_event"]["title"] == "Old Title"
        assert item["expected_provider_revision"] == "v1"

    # Validates: SEL-239
    def test_gcal_404_clears_sync_on_change_undo(self, db, factory):
        user = factory.user()
        event = _event(factory, user)
        _applied_change(factory, user, event, snapshot={**SNAPSHOT, "location": None, "description": None})

        status, _ = _undo(db, event, user, live=None)

        assert status == "active"
        assert _work(db, event) == [], "no provider event left: nothing to write back"
        assert factory.row("events", event)["title"] == "Old Title"

    # Validates: SEL-237
    def test_unsynced_local_only(self, db, factory):
        user = factory.user()
        event = _event(factory, user, google_calendar_event_id=None, synced_at=None,
                       review_status="rejected")

        with patch("selko.services.events.calendars.get_calendar_event") as read:
            status = undo_history_event(db, event, user, force=False)

        assert status == "pending_review"
        read.assert_not_called()
        assert _work(db, event) == []
        assert factory.row("events", event)["review_status"] == "pending_review"

    # Validates: SEL-242
    def test_synced_requires_user_id(self, db, factory):
        user = factory.user()
        event = _event(factory, user)

        with pytest.raises(EventsError, match="user_id is required"):
            undo_history_event(db, event)

    # Validates: SEL-242
    def test_another_users_event_is_not_found(self, db, factory):
        owner, other = factory.user(), factory.user()
        event = _event(factory, owner, google_calendar_event_id=None, synced_at=None)

        with pytest.raises(EventsError, match="not found"):
            undo_history_event(db, event, other)
        assert factory.row("events", event)["review_status"] == "active"
