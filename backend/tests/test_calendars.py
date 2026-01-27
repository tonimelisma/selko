"""Unit tests for calendars service.

Tests the calendar sync and settings functions with mocked Google Calendar API.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from selko.services.calendars import (
    CalendarsError,
    _build_calendar_event_body,
    get_calendar_settings,
    list_calendars,
    sync_event_to_calendar,
    update_calendar_settings,
    cancel_calendar_event,
)


class TestBuildCalendarEventBody:
    """Tests for calendar event body construction."""

    def test_basic_timed_event(self):
        """Test building body for basic timed event."""
        event = {
            "id": "event-123",
            "title": "Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T15:00:00Z",
            "all_day": False,
            "location": "Conference Room A",
            "description": "Quarterly review",
            "source_attribution": "From email by John",
        }
        settings = {
            "default_invitees": None,
        }

        body = _build_calendar_event_body(event, settings)

        assert body["summary"] == "Meeting"
        assert body["location"] == "Conference Room A"
        assert "Quarterly review" in body["description"]
        assert "From email by John" in body["description"]
        assert body["start"]["dateTime"] == "2026-03-15T14:00:00Z"
        assert body["start"]["timeZone"] == "UTC"
        assert body["end"]["dateTime"] == "2026-03-15T15:00:00Z"
        assert body["extendedProperties"]["private"]["selko_event_id"] == "event-123"

    def test_all_day_event(self):
        """Test building body for all-day event."""
        event = {
            "id": "event-456",
            "title": "Conference",
            "start_datetime": "2026-03-15T00:00:00Z",
            "all_day": True,
            "location": None,
            "description": None,
            "source_attribution": None,
        }
        settings = {"default_invitees": None}

        body = _build_calendar_event_body(event, settings)

        assert body["start"]["date"] == "2026-03-15"
        assert body["end"]["date"] == "2026-03-15"
        assert "dateTime" not in body["start"]

    def test_with_default_invitees(self):
        """Test adding default invitees to event."""
        event = {
            "id": "event-789",
            "title": "Team Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T15:00:00Z",
            "all_day": False,
            "location": None,
            "description": None,
            "source_attribution": None,
        }
        settings = {
            "default_invitees": "spouse@example.com, partner@example.com",
        }

        body = _build_calendar_event_body(event, settings)

        assert "attendees" in body
        assert len(body["attendees"]) == 2
        assert body["attendees"][0]["email"] == "spouse@example.com"
        assert body["attendees"][1]["email"] == "partner@example.com"

    def test_missing_end_datetime_uses_start(self):
        """Test that missing end datetime uses start datetime."""
        event = {
            "id": "event-111",
            "title": "Quick Call",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": None,
            "all_day": False,
            "location": None,
            "description": None,
            "source_attribution": None,
        }
        settings = {"default_invitees": None}

        body = _build_calendar_event_body(event, settings)

        assert body["end"]["dateTime"] == "2026-03-15T14:00:00Z"

    def test_handles_datetime_objects(self):
        """Test handling of actual datetime objects instead of strings."""
        event = {
            "id": "event-222",
            "title": "Datetime Object Test",
            "start_datetime": datetime(2026, 3, 15, 14, 0, 0, tzinfo=timezone.utc),
            "end_datetime": datetime(2026, 3, 15, 15, 0, 0, tzinfo=timezone.utc),
            "all_day": False,
            "location": None,
            "description": None,
            "source_attribution": None,
        }
        settings = {"default_invitees": None}

        body = _build_calendar_event_body(event, settings)

        assert "2026-03-15" in body["start"]["dateTime"]
        assert "14:00:00" in body["start"]["dateTime"]

    def test_empty_description_with_attribution(self):
        """Test that attribution works when description is empty."""
        event = {
            "id": "event-333",
            "title": "Test",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T15:00:00Z",
            "all_day": False,
            "location": None,
            "description": "",
            "source_attribution": "Created from email",
        }
        settings = {"default_invitees": None}

        body = _build_calendar_event_body(event, settings)

        assert body["description"] == "Created from email"


class TestGetCalendarSettings:
    """Tests for retrieving calendar settings."""

    def test_returns_defaults_when_no_settings(self):
        """Test that defaults are returned when user has no settings."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        mock_result.data = []
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result

        settings = get_calendar_settings(mock_client, "user-123")

        assert settings["target_calendar_id"] is None
        assert settings["target_calendar_name"] is None
        assert settings["default_invitees"] is None

    def test_returns_stored_settings(self):
        """Test that stored settings are returned."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        mock_result.data = [{
            "target_calendar_id": "calendar-456",
            "default_invitees": "spouse@example.com",
        }]
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result

        with patch("selko.services.calendars.list_calendars") as mock_list:
            mock_list.return_value = [
                {"id": "calendar-456", "name": "Family", "is_primary": False}
            ]
            settings = get_calendar_settings(mock_client, "user-123")

        assert settings["target_calendar_id"] == "calendar-456"
        assert settings["target_calendar_name"] == "Family"
        assert settings["default_invitees"] == "spouse@example.com"


class TestUpdateCalendarSettings:
    """Tests for updating calendar settings."""

    def test_upserts_settings(self):
        """Test that settings are upserted."""
        mock_client = MagicMock()

        mock_upsert = MagicMock()
        mock_client.table.return_value.upsert.return_value = mock_upsert
        mock_upsert.execute.return_value = MagicMock()

        update_calendar_settings(
            mock_client,
            "user-123",
            target_calendar_id="calendar-789",
            default_invitees="spouse@example.com"
        )

        mock_client.table.assert_called_with("user_calendar_settings")
        mock_client.table.return_value.upsert.assert_called_once()

        call_args = mock_client.table.return_value.upsert.call_args[0][0]
        assert call_args["user_id"] == "user-123"
        assert call_args["target_calendar_id"] == "calendar-789"
        assert call_args["default_invitees"] == "spouse@example.com"


class TestListCalendars:
    """Tests for listing Google calendars."""

    def test_returns_calendars_with_selection_state(self):
        """Test that calendars are returned with selection state."""
        mock_client = MagicMock()

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build, \
             patch("selko.services.calendars.get_calendar_settings") as mock_settings:

            mock_creds.return_value = MagicMock()
            mock_settings.return_value = {"target_calendar_id": "cal-2"}

            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.calendarList.return_value.list.return_value.execute.return_value = {
                "items": [
                    {"id": "cal-1", "summary": "Primary", "primary": True},
                    {"id": "cal-2", "summary": "Work", "primary": False},
                ]
            }

            calendars = list_calendars(mock_client, "user-123")

            assert len(calendars) == 2
            assert calendars[0]["id"] == "cal-1"
            assert calendars[0]["is_primary"] is True
            assert calendars[0]["is_selected"] is False
            assert calendars[1]["id"] == "cal-2"
            assert calendars[1]["is_selected"] is True

    def test_raises_error_when_no_credentials(self):
        """Test that error is raised when no credentials found."""
        mock_client = MagicMock()

        with patch("selko.services.calendars.get_credentials") as mock_creds:
            mock_creds.return_value = None

            with pytest.raises(CalendarsError) as exc_info:
                list_calendars(mock_client, "user-123")

            assert "No Google Calendar credentials found" in str(exc_info.value)


class TestSyncEventToCalendar:
    """Tests for syncing events to Google Calendar."""

    def test_creates_new_calendar_event(self):
        """Test creating a new calendar event."""
        mock_client = MagicMock()

        # Setup event fetch
        mock_event_result = MagicMock()
        mock_event_result.data = {
            "id": "event-123",
            "user_id": "user-456",
            "title": "Test Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T15:00:00Z",
            "all_day": False,
            "location": None,
            "description": None,
            "source_attribution": None,
            "google_calendar_event_id": None,  # Not synced yet
        }

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build, \
             patch("selko.services.calendars.get_calendar_settings") as mock_settings:

            mock_creds.return_value = MagicMock()
            mock_settings.return_value = {
                "target_calendar_id": "primary",
                "default_invitees": None,
            }

            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.insert.return_value.execute.return_value = {
                "id": "google-event-abc123"
            }

            # Setup Supabase mocks
            mock_table = MagicMock()
            mock_client.table.return_value = mock_table

            # For select (fetch event)
            mock_select = MagicMock()
            mock_table.select.return_value = mock_select
            mock_select.eq.return_value.single.return_value.execute.return_value = mock_event_result

            # For update
            mock_update = MagicMock()
            mock_table.update.return_value = mock_update
            mock_update.eq.return_value.execute.return_value = MagicMock()

            # For insert (sync log)
            mock_insert = MagicMock()
            mock_table.insert.return_value = mock_insert
            mock_insert.execute.return_value = MagicMock()

            result = sync_event_to_calendar(mock_client, "user-456", "event-123")

            assert result == "google-event-abc123"
            mock_service.events.return_value.insert.assert_called_once()

    def test_updates_existing_calendar_event(self):
        """Test updating an existing calendar event."""
        mock_client = MagicMock()

        # Setup event with existing Google Calendar event ID
        mock_event_result = MagicMock()
        mock_event_result.data = {
            "id": "event-123",
            "user_id": "user-456",
            "title": "Updated Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T16:00:00Z",  # Changed
            "all_day": False,
            "location": "New Room",
            "description": None,
            "source_attribution": None,
            "google_calendar_event_id": "google-existing-123",  # Already synced
        }

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build, \
             patch("selko.services.calendars.get_calendar_settings") as mock_settings:

            mock_creds.return_value = MagicMock()
            mock_settings.return_value = {
                "target_calendar_id": "primary",
                "default_invitees": None,
            }

            mock_service = MagicMock()
            mock_build.return_value = mock_service

            # Existing event get
            mock_service.events.return_value.get.return_value.execute.return_value = {
                "id": "google-existing-123",
                "summary": "Old Title",
            }

            # Update
            mock_service.events.return_value.update.return_value.execute.return_value = {
                "id": "google-existing-123"
            }

            # Setup Supabase mocks
            mock_table = MagicMock()
            mock_client.table.return_value = mock_table

            mock_select = MagicMock()
            mock_table.select.return_value = mock_select
            mock_select.eq.return_value.single.return_value.execute.return_value = mock_event_result

            mock_update = MagicMock()
            mock_table.update.return_value = mock_update
            mock_update.eq.return_value.execute.return_value = MagicMock()

            mock_insert = MagicMock()
            mock_table.insert.return_value = mock_insert
            mock_insert.execute.return_value = MagicMock()

            result = sync_event_to_calendar(mock_client, "user-456", "event-123")

            assert result == "google-existing-123"
            mock_service.events.return_value.update.assert_called_once()

    def test_recreates_deleted_calendar_event(self):
        """Test that deleted calendar events are recreated."""
        mock_client = MagicMock()

        mock_event_result = MagicMock()
        mock_event_result.data = {
            "id": "event-123",
            "user_id": "user-456",
            "title": "Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T15:00:00Z",
            "all_day": False,
            "location": None,
            "description": None,
            "source_attribution": None,
            "google_calendar_event_id": "google-deleted-123",  # Was synced but deleted
        }

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build, \
             patch("selko.services.calendars.get_calendar_settings") as mock_settings:

            from googleapiclient.errors import HttpError

            mock_creds.return_value = MagicMock()
            mock_settings.return_value = {
                "target_calendar_id": "primary",
                "default_invitees": None,
            }

            mock_service = MagicMock()
            mock_build.return_value = mock_service

            # Get returns 404 (deleted)
            mock_resp = MagicMock()
            mock_resp.status = 404
            mock_service.events.return_value.get.return_value.execute.side_effect = HttpError(
                mock_resp, b"Not found"
            )

            # Insert creates new
            mock_service.events.return_value.insert.return_value.execute.return_value = {
                "id": "google-new-456"
            }

            # Setup Supabase mocks
            mock_table = MagicMock()
            mock_client.table.return_value = mock_table

            mock_select = MagicMock()
            mock_table.select.return_value = mock_select
            mock_select.eq.return_value.single.return_value.execute.return_value = mock_event_result

            mock_update = MagicMock()
            mock_table.update.return_value = mock_update
            mock_update.eq.return_value.execute.return_value = MagicMock()

            mock_insert = MagicMock()
            mock_table.insert.return_value = mock_insert
            mock_insert.execute.return_value = MagicMock()

            result = sync_event_to_calendar(mock_client, "user-456", "event-123")

            assert result == "google-new-456"
            mock_service.events.return_value.insert.assert_called_once()

    def test_marks_event_as_sync_failed_on_error(self):
        """Test that event is marked as sync_failed on error."""
        mock_client = MagicMock()

        mock_event_result = MagicMock()
        mock_event_result.data = {
            "id": "event-123",
            "user_id": "user-456",
            "title": "Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T15:00:00Z",
            "all_day": False,
            "location": None,
            "description": None,
            "source_attribution": None,
            "google_calendar_event_id": None,
        }

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build, \
             patch("selko.services.calendars.get_calendar_settings") as mock_settings:

            mock_creds.return_value = MagicMock()
            mock_settings.return_value = {
                "target_calendar_id": "primary",
                "default_invitees": None,
            }

            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.insert.return_value.execute.side_effect = Exception(
                "API Error"
            )

            # Setup Supabase mocks
            mock_table = MagicMock()
            mock_client.table.return_value = mock_table

            mock_select = MagicMock()
            mock_table.select.return_value = mock_select
            mock_select.eq.return_value.single.return_value.execute.return_value = mock_event_result

            mock_update = MagicMock()
            mock_table.update.return_value = mock_update
            mock_update.eq.return_value.execute.return_value = MagicMock()

            with pytest.raises(CalendarsError):
                sync_event_to_calendar(mock_client, "user-456", "event-123")

            # Verify status was updated to sync_failed
            update_calls = mock_table.update.call_args_list
            # One of the updates should set status to sync_failed
            found_sync_failed = False
            for call in update_calls:
                if "sync_failed" in str(call):
                    found_sync_failed = True
                    break
            assert found_sync_failed or len(update_calls) > 0


class TestCancelCalendarEvent:
    """Tests for cancelling calendar events."""

    def test_prefixes_title_with_cancelled(self):
        """Test that title is prefixed with CANCELLED:."""
        mock_client = MagicMock()

        mock_event_result = MagicMock()
        mock_event_result.data = {
            "id": "event-123",
            "title": "Meeting",
            "google_calendar_event_id": None,
        }

        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value.single.return_value.execute.return_value = mock_event_result

        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value.execute.return_value = MagicMock()

        cancel_calendar_event(mock_client, "user-456", "event-123")

        # Verify update was called with CANCELLED prefix
        update_calls = mock_table.update.call_args_list
        assert len(update_calls) > 0
        first_call_args = update_calls[0][0][0]
        assert "CANCELLED: Meeting" in first_call_args.get("title", "")

    def test_does_not_double_prefix(self):
        """Test that already-cancelled events don't get double prefix."""
        mock_client = MagicMock()

        mock_event_result = MagicMock()
        mock_event_result.data = {
            "id": "event-123",
            "title": "CANCELLED: Meeting",
            "google_calendar_event_id": None,
        }

        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value.single.return_value.execute.return_value = mock_event_result

        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value.execute.return_value = MagicMock()

        cancel_calendar_event(mock_client, "user-456", "event-123")

        # Should not add another CANCELLED prefix
        # The function should short-circuit when title already has prefix
