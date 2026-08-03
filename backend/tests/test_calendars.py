"""Unit tests for calendars service.

Tests the calendar sync and settings functions with mocked Google Calendar API.
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from selko.services.calendars import (
    CalendarAuthRequiredError,
    CalendarsError,
    SELKO_FOOTER,
    _build_calendar_event_body,
    classify_calendar_error,
    delete_calendar_event,
    fetch_calendar_events_for_date_range,
    get_calendar_settings,
    list_calendars,
    refresh_waiting_calendar_recoveries,
    requeue_calendar_recovery_batch,
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
            "timezone": "UTC",
        }

        body = _build_calendar_event_body(event, settings)

        assert body["summary"] == "Meeting"
        assert body["location"] == "Conference Room A"
        assert "Quarterly review" in body["description"]
        assert "From email by John" in body["description"]
        assert body["start"]["dateTime"] == "2026-03-15T14:00:00"
        assert body["start"]["timeZone"] == "UTC"
        assert body["end"]["dateTime"] == "2026-03-15T15:00:00"
        assert body["extendedProperties"]["private"]["selko_event_id"] == "event-123"

    def test_all_day_event(self):
        """Single-day all-day event: local midnight start, exclusive next-day end."""
        event = {
            "id": "event-456",
            "title": "Conference",
            # Local midnight March 15 in America/New_York (EDT, UTC-4)
            "start_datetime": "2026-03-15T04:00:00Z",
            "all_day": True,
            "location": None,
            "description": None,
            "source_attribution": None,
        }
        settings = {"default_invitees": None}

        body = _build_calendar_event_body(event, settings)

        assert body["start"]["date"] == "2026-03-15"
        assert body["end"]["date"] == "2026-03-16"
        assert "dateTime" not in body["start"]

    def test_multi_day_all_day_event_does_not_collapse(self):
        """Regression: a multi-day all-day event must not collapse to one day."""
        event = {
            "id": "event-789",
            "title": "Kids Club Closed",
            "start_datetime": "2026-08-12T07:00:00Z",
            "end_datetime": "2026-08-15T06:59:59Z",
            "all_day": True,
            "location": None,
            "description": None,
            "source_attribution": None,
        }
        settings = {"default_invitees": None, "timezone": "America/Los_Angeles"}

        body = _build_calendar_event_body(event, settings)

        assert body["start"]["date"] == "2026-08-12"
        assert body["end"]["date"] == "2026-08-15"

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
        settings = {"default_invitees": None, "timezone": "UTC"}

        body = _build_calendar_event_body(event, settings)

        assert body["end"]["dateTime"] == "2026-03-15T14:00:00"
        assert body["end"]["timeZone"] == "UTC"

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
        settings = {"default_invitees": None, "timezone": "UTC"}

        body = _build_calendar_event_body(event, settings)

        assert body["start"]["dateTime"] == "2026-03-15T14:00:00"
        assert body["start"]["timeZone"] == "UTC"

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

        assert body["description"] == "Created from email\n\n---\nThis event is managed by Selko."


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
        assert settings["all_day_display_mode"] == "all_day"
        assert settings["all_day_custom_start"] is None
        assert settings["all_day_custom_end"] is None

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

    def test_provider_401_marks_calendar_integration_expired(self):
        """Calendar-list token rejection must trigger reconnect UI state."""
        from googleapiclient.errors import HttpError

        mock_client = MagicMock()
        mock_response = MagicMock(status=401, reason="Unauthorized")

        with (
            patch("selko.services.calendars.get_credentials", return_value=MagicMock()),
            patch("selko.services.calendars.build") as build,
            patch(
                "selko.services.calendars.update_integration_status"
            ) as update_status,
            pytest.raises(CalendarsError),
        ):
            build.return_value.calendarList.return_value.list.return_value.execute.side_effect = HttpError(
                mock_response, b"Unauthorized"
            )
            list_calendars(mock_client, "user-123")

        update_status.assert_called_once_with(
            mock_client,
            "google_calendar",
            "expired",
            user_id="user-123",
        )


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

    def test_recovers_existing_event_before_retry_insert(self):
        """An ambiguous earlier insert must not create a duplicate on retry."""
        mock_client = MagicMock()
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
            "google_calendar_event_id": None,
        }

        with (
            patch(
                "selko.services.calendars.get_credentials",
                return_value=MagicMock(),
            ),
            patch("selko.services.calendars.build") as mock_build,
            patch(
                "selko.services.calendars.get_calendar_settings",
                return_value={
                    "target_calendar_id": "primary",
                    "default_invitees": None,
                },
            ),
        ):
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.list.return_value.execute.return_value = {
                "items": [{"id": "google-recovered-123"}]
            }
            mock_service.events.return_value.get.return_value.execute.return_value = {
                "id": "google-recovered-123"
            }
            mock_service.events.return_value.update.return_value.execute.return_value = {
                "id": "google-recovered-123"
            }

            mock_table = MagicMock()
            mock_client.table.return_value = mock_table
            mock_table.select.return_value.eq.return_value.single.return_value.execute.return_value = (
                mock_event_result
            )
            mock_table.update.return_value.eq.return_value.execute.return_value = (
                MagicMock()
            )
            mock_table.insert.return_value.execute.return_value = MagicMock()

            result = sync_event_to_calendar(
                mock_client, "user-456", "event-123"
            )

        assert result == "google-recovered-123"
        mock_service.events.return_value.list.assert_called_once_with(
            calendarId="primary",
            privateExtendedProperty="selko_event_id=event-123",
            showDeleted=False,
            maxResults=2,
        )
        mock_service.events.return_value.insert.assert_not_called()
        mock_service.events.return_value.update.assert_called_once()

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

            mock_table.update.assert_called_with({
                "status": "sync_failed",
                "sync_error": "API Error",
                "sync_failure_code": "unknown",
            })

    def test_provider_401_marks_calendar_integration_expired(self):
        """A direct Google API token rejection must trigger reconnect UI state."""
        from googleapiclient.errors import HttpError

        mock_client = MagicMock()
        mock_event_result = MagicMock(data={
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
        })
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_event_result
        mock_response = MagicMock(status=401, reason="Unauthorized")

        with (
            patch("selko.services.calendars.get_credentials", return_value=MagicMock()),
            patch(
                "selko.services.calendars.get_calendar_settings",
                return_value={"target_calendar_id": "primary"},
            ),
            patch("selko.services.calendars.build") as build,
            patch(
                "selko.services.calendars.update_integration_status"
            ) as update_status,
            pytest.raises(CalendarsError),
        ):
            build.return_value.events.return_value.insert.return_value.execute.side_effect = HttpError(
                mock_response, b"Unauthorized"
            )
            sync_event_to_calendar(mock_client, "user-456", "event-123")

        update_status.assert_called_once_with(
            mock_client,
            "google_calendar",
            "expired",
            user_id="user-456",
        )


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


class TestDeleteCalendarEvent:
    """Tests for deleting calendar events from Google Calendar."""

    def test_successful_delete(self):
        """Test successful deletion of a synced event."""
        mock_client = MagicMock()

        mock_event_result = MagicMock()
        mock_event_result.data = {
            "id": "event-123",
            "title": "Meeting",
            "google_calendar_event_id": "google-event-abc",
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

            # Delete succeeds
            mock_service.events.return_value.delete.return_value.execute.return_value = None

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

            delete_calendar_event(mock_client, "user-456", "event-123")

            # Verify Google Calendar delete was called
            mock_service.events.return_value.delete.assert_called_once_with(
                calendarId="primary", eventId="google-event-abc"
            )

            # Verify event record was updated (sync fields cleared, then status)
            update_calls = mock_table.update.call_args_list
            assert len(update_calls) >= 2
            clear_data = update_calls[0][0][0]
            assert clear_data["google_calendar_event_id"] is None
            assert clear_data["synced_at"] is None
            status_data = update_calls[1][0][0]
            assert status_data["status"] == "pending_review"

    def test_delete_already_deleted_from_google(self):
        """Test that 404 from Google Calendar is handled gracefully."""
        mock_client = MagicMock()

        mock_event_result = MagicMock()
        mock_event_result.data = {
            "id": "event-123",
            "title": "Meeting",
            "google_calendar_event_id": "google-event-gone",
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

            # Delete returns 404 (already deleted)
            mock_resp = MagicMock()
            mock_resp.status = 404
            mock_service.events.return_value.delete.return_value.execute.side_effect = HttpError(
                mock_resp, b"Not found"
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

            mock_insert = MagicMock()
            mock_table.insert.return_value = mock_insert
            mock_insert.execute.return_value = MagicMock()

            # Should NOT raise - 404 is handled gracefully
            delete_calendar_event(mock_client, "user-456", "event-123")

            # Verify event record was still updated (clear sync fields, then status)
            update_calls = mock_table.update.call_args_list
            assert len(update_calls) >= 2
            assert update_calls[0][0][0]["google_calendar_event_id"] is None
            assert update_calls[1][0][0]["status"] == "pending_review"

    def test_delete_no_credentials(self):
        """Test that error is raised when no credentials found."""
        mock_client = MagicMock()

        mock_event_result = MagicMock()
        mock_event_result.data = {
            "id": "event-123",
            "title": "Meeting",
            "google_calendar_event_id": "google-event-abc",
        }

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.get_calendar_settings") as mock_settings:

            mock_creds.return_value = None
            mock_settings.return_value = {
                "target_calendar_id": "primary",
                "default_invitees": None,
            }

            mock_table = MagicMock()
            mock_client.table.return_value = mock_table

            mock_select = MagicMock()
            mock_table.select.return_value = mock_select
            mock_select.eq.return_value.single.return_value.execute.return_value = mock_event_result

            with pytest.raises(CalendarsError) as exc_info:
                delete_calendar_event(mock_client, "user-456", "event-123")

            assert "No Google Calendar credentials found" in str(exc_info.value)

    def test_delete_no_google_event_id(self):
        """Test that error is raised when event has no google_calendar_event_id."""
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

        with pytest.raises(CalendarsError) as exc_info:
            delete_calendar_event(mock_client, "user-456", "event-123")

        assert "not synced" in str(exc_info.value)

    def test_delete_logs_sync_operation(self):
        """Test that delete operation is logged to calendar_sync_log."""
        mock_client = MagicMock()

        mock_event_result = MagicMock()
        mock_event_result.data = {
            "id": "event-123",
            "title": "Meeting",
            "google_calendar_event_id": "google-event-abc",
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
            mock_service.events.return_value.delete.return_value.execute.return_value = None

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

            delete_calendar_event(mock_client, "user-456", "event-123")

            # Verify sync log was written
            insert_calls = mock_table.insert.call_args_list
            assert len(insert_calls) > 0
            log_data = insert_calls[0][0][0]
            assert log_data["action"] == "deleted"
            assert log_data["google_calendar_event_id"] == "google-event-abc"
            assert log_data["event_id"] == "event-123"

    def test_delete_google_api_error_raises(self):
        """Test that non-404 Google API errors are re-raised."""
        mock_client = MagicMock()

        mock_event_result = MagicMock()
        mock_event_result.data = {
            "id": "event-123",
            "title": "Meeting",
            "google_calendar_event_id": "google-event-abc",
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

            # Delete returns 403 (forbidden)
            mock_resp = MagicMock()
            mock_resp.status = 403
            mock_service.events.return_value.delete.return_value.execute.side_effect = HttpError(
                mock_resp, b"Forbidden"
            )

            mock_table = MagicMock()
            mock_client.table.return_value = mock_table

            mock_select = MagicMock()
            mock_table.select.return_value = mock_select
            mock_select.eq.return_value.single.return_value.execute.return_value = mock_event_result

            with pytest.raises(CalendarsError) as exc_info:
                delete_calendar_event(mock_client, "user-456", "event-123")

            assert "Failed to delete calendar event" in str(exc_info.value)


class TestFetchCalendarEventsForDateRange:
    """Tests for Google Calendar read-back."""

    def test_fetches_events_successfully(self):
        """Test successful GCal events fetch."""
        mock_client = MagicMock()

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build, \
             patch("selko.services.calendars.get_calendar_settings") as mock_settings:

            mock_creds.return_value = MagicMock()
            mock_settings.return_value = {"target_calendar_id": "primary"}

            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.list.return_value.execute.return_value = {
                "items": [
                    {"id": "gcal-1", "summary": "Meeting"},
                    {"id": "gcal-2", "summary": "Lunch"},
                ]
            }

            result = fetch_calendar_events_for_date_range(
                mock_client, "user-123",
                "2026-03-15T00:00:00Z", "2026-03-15T23:59:59Z"
            )

            assert len(result) == 2
            assert result[0]["id"] == "gcal-1"

            # Verify API called with correct parameters
            mock_service.events.return_value.list.assert_called_once_with(
                calendarId="primary",
                timeMin="2026-03-15T00:00:00Z",
                timeMax="2026-03-15T23:59:59Z",
                singleEvents=True,
                maxResults=50,
                timeZone="America/New_York",
            )

    def test_returns_empty_no_credentials(self):
        """Test that missing credentials return empty list."""
        mock_client = MagicMock()

        with patch("selko.services.calendars.get_credentials") as mock_creds:
            mock_creds.return_value = None

            result = fetch_calendar_events_for_date_range(
                mock_client, "user-123",
                "2026-03-15T00:00:00Z", "2026-03-15T23:59:59Z"
            )

        assert result == []

    def test_returns_empty_on_api_error(self):
        """Test that API errors return empty list (non-fatal)."""
        mock_client = MagicMock()

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build, \
             patch("selko.services.calendars.get_calendar_settings") as mock_settings:

            mock_creds.return_value = MagicMock()
            mock_settings.return_value = {"target_calendar_id": "primary"}

            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.list.return_value.execute.side_effect = Exception("API error")

            result = fetch_calendar_events_for_date_range(
                mock_client, "user-123",
                "2026-03-15T00:00:00Z", "2026-03-15T23:59:59Z"
            )

        assert result == []


class TestSelkoFooter:
    """Tests for Selko footer on calendar events."""

    def test_footer_appended_to_description(self):
        """Test that Selko footer is appended to event description."""
        event = {
            "id": "event-123",
            "title": "Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T15:00:00Z",
            "all_day": False,
            "location": None,
            "description": "Weekly sync",
            "source_attribution": None,
        }
        settings = {"default_invitees": None}

        body = _build_calendar_event_body(event, settings)

        assert "This event is managed by Selko." in body["description"]
        assert "Weekly sync" in body["description"]

    def test_no_duplicate_footer(self):
        """Test that footer is not duplicated on re-sync."""
        # Description already contains the footer
        event = {
            "id": "event-123",
            "title": "Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T15:00:00Z",
            "all_day": False,
            "location": None,
            "description": "Weekly sync\n\n---\nThis event is managed by Selko.",
            "source_attribution": None,
        }
        settings = {"default_invitees": None}

        body = _build_calendar_event_body(event, settings)

        # Count occurrences of footer
        count = body["description"].count("This event is managed by Selko.")
        assert count == 1

    def test_footer_on_empty_description(self):
        """Test footer works when description is empty."""
        event = {
            "id": "event-123",
            "title": "Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T15:00:00Z",
            "all_day": False,
            "location": None,
            "description": None,
            "source_attribution": None,
        }
        settings = {"default_invitees": None}

        body = _build_calendar_event_body(event, settings)

        assert "This event is managed by Selko." in body["description"]


def _http_error(status: int, reason: str | None = None, message: str = "error"):
    """Build a googleapiclient HttpError shaped like a real Google API response."""
    from googleapiclient.errors import HttpError

    resp = MagicMock(status=status, reason=message)
    error_body: dict = {"code": status, "message": message}
    if reason:
        error_body["errors"] = [{"reason": reason, "message": message}]
    content = json.dumps({"error": error_body}).encode("utf-8")
    return HttpError(resp, content)


class TestClassifyCalendarError:
    """Structured failure taxonomy (docs/specs/oauth-reconnect-catch-up.md, section 1).

    Control flow must branch on ``classify_calendar_error(...).code``, never
    on ``str(exc)`` — these tests pin the exact classification for each shape
    of failure a calendar sync can hit.
    """

    def test_auth_required_error_is_oauth_required_and_isolated_from_circuit(self):
        result = classify_calendar_error(CalendarAuthRequiredError("no creds"))
        assert result.code == "oauth_required"
        assert result.retryable is False
        assert result.counts_toward_circuit_breaker is False

    def test_http_401_is_oauth_required_and_isolated_from_circuit(self):
        result = classify_calendar_error(_http_error(401))
        assert result.code == "oauth_required"
        assert result.counts_toward_circuit_breaker is False

    def test_http_403_insufficient_scope_is_distinct_from_permission_denied(self):
        result = classify_calendar_error(
            _http_error(403, reason="insufficientPermissions")
        )
        assert result.code == "oauth_scope_required"
        assert result.retryable is False
        assert result.counts_toward_circuit_breaker is False

    def test_http_403_unrelated_reason_is_terminal_permission_denied(self):
        result = classify_calendar_error(_http_error(403, reason="forbidden"))
        assert result.code == "permission_denied"
        assert result.counts_toward_circuit_breaker is False

    def test_http_429_is_rate_limited_and_counts_toward_circuit_breaker(self):
        result = classify_calendar_error(_http_error(429))
        assert result.code == "rate_limited"
        assert result.retryable is True
        assert result.counts_toward_circuit_breaker is True

    def test_http_503_is_provider_transient_and_counts_toward_circuit_breaker(self):
        result = classify_calendar_error(_http_error(503))
        assert result.code == "provider_transient"
        assert result.counts_toward_circuit_breaker is True

    def test_http_400_is_invalid_event_and_not_a_circuit_signal(self):
        result = classify_calendar_error(_http_error(400))
        assert result.code == "invalid_event"
        assert result.counts_toward_circuit_breaker is False

    def test_unclassified_exception_defaults_to_unknown_and_counts(self):
        result = classify_calendar_error(Exception("boom"))
        assert result.code == "unknown"
        assert result.counts_toward_circuit_breaker is True


class TestSyncEventToCalendarOAuthScopeRequired:
    """An insufficient-scope 403 must be tagged distinctly from a plain sync failure."""

    def test_marks_integration_expired_and_tags_event_without_dead_lettering(self):
        mock_client = MagicMock()
        mock_event_result = MagicMock(data={
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
        })
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_event_result

        with (
            patch("selko.services.calendars.get_credentials", return_value=MagicMock()),
            patch(
                "selko.services.calendars.get_calendar_settings",
                return_value={"target_calendar_id": "primary"},
            ),
            patch("selko.services.calendars.build") as build,
            patch(
                "selko.services.calendars.update_integration_status"
            ) as update_status,
            pytest.raises(CalendarsError),
        ):
            build.return_value.events.return_value.insert.return_value.execute.side_effect = (
                _http_error(403, reason="insufficientPermissions")
            )
            sync_event_to_calendar(mock_client, "user-456", "event-123")

        update_status.assert_called_once_with(
            mock_client,
            "google_calendar",
            "expired",
            user_id="user-456",
        )
        # Unlike a generic failure, this must not set status=sync_failed:
        # the caller (worker pool) returns the event to `approved` without
        # spending a retry attempt.
        update_call = mock_table.update.call_args.args[0]
        assert "status" not in update_call
        assert update_call["sync_failure_code"] == "oauth_scope_required"


class TestRequeueCalendarRecoveryBatch:
    """RPC wrapper for the calendar recovery worker's tagging step."""

    def test_returns_tagged_count_from_rpc(self):
        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.return_value = MagicMock(data=42)

        result = requeue_calendar_recovery_batch(
            mock_client, "recovery-1", "worker-1", batch_size=50
        )

        assert result == 42
        mock_client.rpc.assert_called_once_with(
            "requeue_calendar_recovery_batch",
            {
                "p_recovery_id": "recovery-1",
                "p_worker_id": "worker-1",
                "p_batch_size": 50,
            },
        )

    def test_wraps_rpc_failure(self):
        from postgrest.exceptions import APIError

        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.side_effect = APIError({"message": "boom"})

        with pytest.raises(CalendarsError):
            requeue_calendar_recovery_batch(mock_client, "recovery-1", "worker-1")


class TestRefreshWaitingCalendarRecoveries:
    """RPC wrapper for the calendar recovery worker's completion-check step."""

    def test_returns_processed_count_from_rpc(self):
        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.return_value = MagicMock(data=5)

        result = refresh_waiting_calendar_recoveries(mock_client, batch_size=10)

        assert result == 5
        mock_client.rpc.assert_called_once_with(
            "refresh_waiting_calendar_recoveries", {"p_batch_size": 10}
        )

    def test_defaults_to_zero_when_rpc_returns_none(self):
        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.return_value = MagicMock(data=None)

        assert refresh_waiting_calendar_recoveries(mock_client) == 0
