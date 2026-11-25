"""Integration tests for calendar sync functionality.

The calendar settings and sync flow run on a real SQLite database (the
`db`/`factory` fixtures) with Google Calendar's API mocked.
"""

from unittest.mock import MagicMock, patch

import pytest

from selko.db import calendar_work
from selko.services.calendars import (
    CalendarsError,
    get_calendar_settings,
    sync_event_to_calendar,
    update_calendar_settings,
    cancel_event_to_calendar,
)


@pytest.fixture
def user_id(factory):
    user_id = factory.user()
    factory.integration(user_id, provider="google_calendar", scopes=["calendar"])
    return user_id


def _sync_log(db, event_id):
    return [
        db.schema.decode("calendar_sync_log", row)
        for row in db.query(
            "SELECT * FROM calendar_sync_log WHERE event_id = ? ORDER BY rowid", (event_id,)
        )
    ]


@pytest.mark.integration
class TestCalendarSettings:
    """Test calendar settings CRUD operations."""

    def test_get_default_settings_when_none_exist(self, db, user_id):
        """Test that default settings are returned when user has none."""
        with patch("selko.services.calendars.list_calendars") as mock_list:
            mock_list.return_value = []
            settings = get_calendar_settings(db, user_id)

        assert settings["target_calendar_id"] is None
        assert settings["target_calendar_name"] is None
        assert settings["default_invitees"] is None

    def test_update_and_get_settings(self, db, user_id):
        """Test updating and retrieving calendar settings."""
        update_calendar_settings(
            db,
            user_id,
            target_calendar_id="test-calendar-123",
            default_invitees="spouse@example.com, partner@example.com",
        )

        with patch("selko.services.calendars.list_calendars") as mock_list:
            mock_list.return_value = [
                {"id": "test-calendar-123", "name": "Family Calendar", "is_primary": False}
            ]
            settings = get_calendar_settings(db, user_id)

        assert settings["target_calendar_id"] == "test-calendar-123"
        assert settings["target_calendar_name"] == "Family Calendar"
        assert settings["default_invitees"] == "spouse@example.com, partner@example.com"

    def test_update_settings_idempotent(self, db, user_id):
        """Test that updating settings multiple times is idempotent."""
        update_calendar_settings(
            db, user_id, target_calendar_id="calendar-1", default_invitees="first@example.com",
        )
        update_calendar_settings(
            db, user_id, target_calendar_id="calendar-2", default_invitees="second@example.com",
        )

        rows = db.query("SELECT * FROM user_calendar_settings WHERE user_id = ?", (user_id,))
        assert len(rows) == 1
        assert rows[0]["target_calendar_id"] == "calendar-2"
        assert rows[0]["default_invitees"] == "second@example.com"


@pytest.mark.integration
class TestCalendarSync:
    """Test calendar sync with mocked Google Calendar API."""

    def test_sync_creates_new_google_event(self, db, factory, user_id):
        """Test syncing an approved event creates a new Google Calendar event."""
        event_id = factory.event(
            user_id,
            review_status="active",
            title="Test Sync Event",
            start_datetime="2026-03-15T14:00:00.000000Z",
            end_datetime="2026-03-15T15:00:00.000000Z",
            all_day=False,
            location="Test Location",
            description="Test description",
        )

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.list.return_value.execute.return_value = {"items": []}
            mock_service.events.return_value.insert.return_value.execute.return_value = {
                "id": "google-event-abc123"
            }

            google_event_id = sync_event_to_calendar(db, user_id, event_id)

            assert google_event_id == "google-event-abc123"

        # The provider adapter is deliberately side-effect limited: the
        # worker-owned completion, not this adapter, projects provider
        # identity/status back onto events.
        updated_event = factory.row("events", event_id)
        assert updated_event["review_status"] == "active"
        assert updated_event["google_calendar_event_id"] is None
        assert updated_event["synced_at"] is None

    def test_sync_creates_log_entry(self, db, factory, user_id):
        """Test that sync operation creates an audit log entry."""
        event_id = factory.event(
            user_id, review_status="active", title="Log Test Event",
            start_datetime="2026-03-20T10:00:00.000000Z",
        )

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.list.return_value.execute.return_value = {"items": []}
            mock_service.events.return_value.insert.return_value.execute.return_value = {
                "id": "google-log-test-123"
            }

            sync_event_to_calendar(db, user_id, event_id)

        log = _sync_log(db, event_id)
        assert len(log) == 1
        assert log[0]["google_calendar_event_id"] == "google-log-test-123"
        assert log[0]["action"] == "created"
        assert log[0]["user_id"] == user_id
        assert log[0]["snapshot_synced"]["summary"] == "Log Test Event"

    def test_sync_updates_existing_google_event(self, db, factory, user_id):
        """Test syncing an event that was already synced updates the existing Google event."""
        event_id = factory.event(
            user_id, review_status="active", title="Already Synced Event",
            start_datetime="2026-03-25T14:00:00.000000Z",
            end_datetime="2026-03-25T15:00:00.000000Z",
            google_calendar_event_id="existing-google-event-456",
        )

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.get.return_value.execute.return_value = {
                "id": "existing-google-event-456",
                "summary": "Old Title",
            }
            mock_service.events.return_value.update.return_value.execute.return_value = {
                "id": "existing-google-event-456"
            }

            google_event_id = sync_event_to_calendar(db, user_id, event_id)

            assert google_event_id == "existing-google-event-456"
            mock_service.events.return_value.update.assert_called_once()
        assert [r["action"] for r in _sync_log(db, event_id)] == ["updated"]

    def test_sync_recreates_deleted_google_event(self, db, factory, user_id):
        """Test that sync recreates a Google Calendar event if it was deleted."""
        from googleapiclient.errors import HttpError

        event_id = factory.event(
            user_id, review_status="active", title="Recreate Test Event",
            start_datetime="2026-04-01T14:00:00.000000Z",
            google_calendar_event_id="deleted-google-event-789",
        )

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_resp = MagicMock()
            mock_resp.status = 404
            mock_service.events.return_value.get.return_value.execute.side_effect = HttpError(
                mock_resp, b"Not found"
            )
            mock_service.events.return_value.insert.return_value.execute.return_value = {
                "id": "new-google-event-abc"
            }

            google_event_id = sync_event_to_calendar(db, user_id, event_id)

            assert google_event_id == "new-google-event-abc"
            mock_service.events.return_value.insert.assert_called_once()

        # The provider adapter does not mutate the event projection; the
        # worker completion owns that transition.
        assert factory.row("events", event_id)["google_calendar_event_id"] == "deleted-google-event-789"

    def test_sync_fails_without_credentials(self, db, factory, user_id):
        """Test that sync fails gracefully when no credentials are available.

        Since #236 (structured failure classification) a missing credential
        is an `oauth_required` failure: the worker parks the item for
        reauthorization instead of consuming a retry toward dead-letter.
        """
        event_id = factory.event(
            user_id, review_status="active", title="No Credentials Event",
            start_datetime="2026-04-05T14:00:00.000000Z",
        )
        before = factory.row("events", event_id)

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
                patch("selko.services.calendars.update_integration_status"):
            mock_creds.return_value = None

            with pytest.raises(CalendarsError) as exc_info:
                sync_event_to_calendar(db, user_id, event_id)

            assert "No Google Calendar credentials found" in str(exc_info.value)
            assert exc_info.value.classification.code == "oauth_required"

        # The provider adapter reports the auth failure; work-item failure
        # state is written only by the worker's fenced transition.
        assert factory.row("events", event_id) == before


@pytest.mark.integration
class TestCancelCalendarEvent:
    """The worker-owned calendar cancellation write.

    Inline cancellation (which rewrote the local title and status) was
    removed; the local transition is `complete_calendar_work`'s.
    """

    def test_cancel_prefixes_title(self, db, factory, user_id):
        """The calendar copy gets the prefix; the local row is completed by the worker."""
        event_id = factory.event(
            user_id, review_status="active", title="Meeting to Cancel",
            start_datetime="2026-04-10T14:00:00.000000Z",
            google_calendar_event_id="google-cancel-1",
        )
        queued = calendar_work.queue_event_cancellation(db, user_id, event_id)
        item, _ = calendar_work.claim_calendar_work_item(db, "cancel-worker")
        assert item["id"] == queued["work_item_id"]

        with patch("selko.services.calendars.get_credentials", return_value=MagicMock()), \
                patch("selko.services.calendars.build") as mock_build:
            service = mock_build.return_value
            service.events.return_value.get.return_value.execute.return_value = {
                "id": "google-cancel-1", "summary": "Meeting to Cancel",
            }
            cancel_event_to_calendar(db, user_id, event_id)

        assert factory.row("events", event_id)["title"] == "Meeting to Cancel"
        assert calendar_work.complete_calendar_work(
            db, item["id"], "cancel-worker", item["generation"], None
        ) is True
        final = factory.row("events", event_id)
        assert final["title"] == "Meeting to Cancel"
        assert final["review_status"] == "cancelled"
        assert final["google_calendar_event_id"] is None

    def test_cancel_updates_google_calendar_event(self, db, factory, user_id):
        """Test that cancelling updates the Google Calendar event title."""
        event_id = factory.event(
            user_id, review_status="active", title="Synced Meeting",
            start_datetime="2026-04-15T14:00:00.000000Z",
            google_calendar_event_id="google-to-cancel-123",
        )

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.get.return_value.execute.return_value = {
                "id": "google-to-cancel-123",
                "summary": "Synced Meeting",
            }
            mock_service.events.return_value.update.return_value.execute.return_value = {
                "id": "google-to-cancel-123"
            }

            cancel_event_to_calendar(db, user_id, event_id)

            mock_service.events.return_value.update.assert_called_once()
            body = mock_service.events.return_value.update.call_args.kwargs["body"]
            assert body["summary"] == "CANCELLED: Synced Meeting"

    def test_cancel_handles_already_deleted_google_event(self, db, factory, user_id):
        """Test that cancelling handles case where Google event was already deleted."""
        from googleapiclient.errors import HttpError

        event_id = factory.event(
            user_id, review_status="active", title="Already Deleted",
            start_datetime="2026-04-20T14:00:00.000000Z",
            google_calendar_event_id="google-already-deleted-456",
        )

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_resp = MagicMock()
            mock_resp.status = 404
            mock_service.events.return_value.get.return_value.execute.side_effect = HttpError(
                mock_resp, b"Not found"
            )

            # Should not raise: a calendar copy that is already gone is cancelled.
            cancel_event_to_calendar(db, user_id, event_id)
            mock_service.events.return_value.update.assert_not_called()

        assert factory.row("events", event_id)["title"] == "Already Deleted"
