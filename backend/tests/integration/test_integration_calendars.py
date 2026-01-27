"""Integration tests for calendar sync functionality.

Tests the calendar settings and sync flow with real Supabase
but mocked Google Calendar API.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from selko.services.calendars import (
    CalendarsError,
    get_calendar_settings,
    sync_event_to_calendar,
    update_calendar_settings,
    cancel_calendar_event,
)


@pytest.mark.integration
@pytest.mark.development
class TestCalendarSettings:
    """Test calendar settings CRUD operations."""

    def test_get_default_settings_when_none_exist(
        self, authenticated_client, test_user_id
    ):
        """Test that default settings are returned when user has none."""
        # Clear any existing settings
        authenticated_client.table("user_calendar_settings").delete().eq(
            "user_id", test_user_id
        ).execute()

        with patch("selko.services.calendars.list_calendars") as mock_list:
            mock_list.return_value = []
            settings = get_calendar_settings(authenticated_client, test_user_id)

        assert settings["target_calendar_id"] is None
        assert settings["target_calendar_name"] is None
        assert settings["default_invitees"] is None

    def test_update_and_get_settings(self, authenticated_client, test_user_id):
        """Test updating and retrieving calendar settings."""
        # Update settings
        update_calendar_settings(
            authenticated_client,
            test_user_id,
            target_calendar_id="test-calendar-123",
            default_invitees="spouse@example.com, partner@example.com",
        )

        # Retrieve settings
        with patch("selko.services.calendars.list_calendars") as mock_list:
            mock_list.return_value = [
                {"id": "test-calendar-123", "name": "Family Calendar", "is_primary": False}
            ]
            settings = get_calendar_settings(authenticated_client, test_user_id)

        assert settings["target_calendar_id"] == "test-calendar-123"
        assert settings["target_calendar_name"] == "Family Calendar"
        assert settings["default_invitees"] == "spouse@example.com, partner@example.com"

    def test_update_settings_idempotent(self, authenticated_client, test_user_id):
        """Test that updating settings multiple times is idempotent."""
        # First update
        update_calendar_settings(
            authenticated_client,
            test_user_id,
            target_calendar_id="calendar-1",
            default_invitees="first@example.com",
        )

        # Second update
        update_calendar_settings(
            authenticated_client,
            test_user_id,
            target_calendar_id="calendar-2",
            default_invitees="second@example.com",
        )

        # Should have only one row with latest values
        result = authenticated_client.table("user_calendar_settings").select("*").eq(
            "user_id", test_user_id
        ).execute()

        assert len(result.data) == 1
        assert result.data[0]["target_calendar_id"] == "calendar-2"
        assert result.data[0]["default_invitees"] == "second@example.com"


@pytest.mark.integration
@pytest.mark.development
class TestCalendarSync:
    """Test calendar sync with mocked Google Calendar API."""

    def test_sync_creates_new_google_event(self, authenticated_client, test_user_id):
        """Test syncing an approved event creates a new Google Calendar event."""
        # Create an approved event
        event_data = {
            "user_id": test_user_id,
            "title": "Test Sync Event",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T15:00:00Z",
            "all_day": False,
            "location": "Test Location",
            "description": "Test description",
            "status": "approved",
        }

        result = authenticated_client.table("events").insert(event_data).execute()
        event_id = result.data[0]["id"]

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()

            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.insert.return_value.execute.return_value = {
                "id": "google-event-abc123"
            }

            google_event_id = sync_event_to_calendar(
                authenticated_client, test_user_id, event_id
            )

            assert google_event_id == "google-event-abc123"

        # Verify event was updated in database
        updated_event = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()

        assert updated_event.data["status"] == "synced"
        assert updated_event.data["google_calendar_event_id"] == "google-event-abc123"
        assert updated_event.data["synced_at"] is not None

    def test_sync_creates_log_entry(self, authenticated_client, test_user_id):
        """Test that sync operation creates an audit log entry."""
        # Create an approved event
        event_data = {
            "user_id": test_user_id,
            "title": "Log Test Event",
            "start_datetime": "2026-03-20T10:00:00Z",
            "status": "approved",
        }

        result = authenticated_client.table("events").insert(event_data).execute()
        event_id = result.data[0]["id"]

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()

            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.insert.return_value.execute.return_value = {
                "id": "google-log-test-123"
            }

            sync_event_to_calendar(authenticated_client, test_user_id, event_id)

        # Verify log entry was created
        log_result = authenticated_client.table("calendar_sync_log").select("*").eq(
            "event_id", event_id
        ).execute()

        assert len(log_result.data) >= 1
        log_entry = log_result.data[0]
        assert log_entry["google_calendar_event_id"] == "google-log-test-123"
        assert log_entry["action"] == "created"

    def test_sync_updates_existing_google_event(self, authenticated_client, test_user_id):
        """Test syncing an event that was already synced updates the existing Google event."""
        # Create an already-synced event
        event_data = {
            "user_id": test_user_id,
            "title": "Already Synced Event",
            "start_datetime": "2026-03-25T14:00:00Z",
            "end_datetime": "2026-03-25T15:00:00Z",
            "status": "approved",
            "google_calendar_event_id": "existing-google-event-456",
        }

        result = authenticated_client.table("events").insert(event_data).execute()
        event_id = result.data[0]["id"]

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()

            mock_service = MagicMock()
            mock_build.return_value = mock_service

            # Mock get returns existing event
            mock_service.events.return_value.get.return_value.execute.return_value = {
                "id": "existing-google-event-456",
                "summary": "Old Title",
            }

            # Mock update succeeds
            mock_service.events.return_value.update.return_value.execute.return_value = {
                "id": "existing-google-event-456"
            }

            google_event_id = sync_event_to_calendar(
                authenticated_client, test_user_id, event_id
            )

            assert google_event_id == "existing-google-event-456"
            mock_service.events.return_value.update.assert_called_once()

    def test_sync_recreates_deleted_google_event(self, authenticated_client, test_user_id):
        """Test that sync recreates a Google Calendar event if it was deleted."""
        # Create event with google_calendar_event_id pointing to deleted event
        event_data = {
            "user_id": test_user_id,
            "title": "Recreate Test Event",
            "start_datetime": "2026-04-01T14:00:00Z",
            "status": "approved",
            "google_calendar_event_id": "deleted-google-event-789",
        }

        result = authenticated_client.table("events").insert(event_data).execute()
        event_id = result.data[0]["id"]

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            from googleapiclient.errors import HttpError

            mock_creds.return_value = MagicMock()

            mock_service = MagicMock()
            mock_build.return_value = mock_service

            # Mock get returns 404 (event was deleted from Google Calendar)
            mock_resp = MagicMock()
            mock_resp.status = 404
            mock_service.events.return_value.get.return_value.execute.side_effect = HttpError(
                mock_resp, b"Not found"
            )

            # Mock insert creates new event
            mock_service.events.return_value.insert.return_value.execute.return_value = {
                "id": "new-google-event-abc"
            }

            google_event_id = sync_event_to_calendar(
                authenticated_client, test_user_id, event_id
            )

            assert google_event_id == "new-google-event-abc"
            mock_service.events.return_value.insert.assert_called_once()

        # Verify database was updated with new Google event ID
        updated_event = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()

        assert updated_event.data["google_calendar_event_id"] == "new-google-event-abc"

    def test_sync_fails_without_credentials(self, authenticated_client, test_user_id):
        """Test that sync fails gracefully when no credentials are available."""
        # Create an approved event
        event_data = {
            "user_id": test_user_id,
            "title": "No Credentials Event",
            "start_datetime": "2026-04-05T14:00:00Z",
            "status": "approved",
        }

        result = authenticated_client.table("events").insert(event_data).execute()
        event_id = result.data[0]["id"]

        with patch("selko.services.calendars.get_credentials") as mock_creds:
            mock_creds.return_value = None  # No credentials

            with pytest.raises(CalendarsError) as exc_info:
                sync_event_to_calendar(authenticated_client, test_user_id, event_id)

            assert "No Google Calendar credentials found" in str(exc_info.value)

        # Verify event was marked as sync_failed
        updated_event = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()

        assert updated_event.data["status"] == "sync_failed"


@pytest.mark.integration
@pytest.mark.development
class TestCancelCalendarEvent:
    """Test calendar event cancellation."""

    def test_cancel_prefixes_title(self, authenticated_client, test_user_id):
        """Test that cancelling an event prefixes title with CANCELLED:."""
        # Create an event
        event_data = {
            "user_id": test_user_id,
            "title": "Meeting to Cancel",
            "start_datetime": "2026-04-10T14:00:00Z",
            "status": "synced",
        }

        result = authenticated_client.table("events").insert(event_data).execute()
        event_id = result.data[0]["id"]

        cancel_calendar_event(authenticated_client, test_user_id, event_id)

        # Verify title was prefixed
        updated_event = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()

        assert updated_event.data["title"] == "CANCELLED: Meeting to Cancel"
        assert updated_event.data["status"] == "cancelled"

    def test_cancel_updates_google_calendar_event(self, authenticated_client, test_user_id):
        """Test that cancelling updates the Google Calendar event title."""
        # Create synced event with Google Calendar ID
        event_data = {
            "user_id": test_user_id,
            "title": "Synced Meeting",
            "start_datetime": "2026-04-15T14:00:00Z",
            "status": "synced",
            "google_calendar_event_id": "google-to-cancel-123",
        }

        result = authenticated_client.table("events").insert(event_data).execute()
        event_id = result.data[0]["id"]

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()

            mock_service = MagicMock()
            mock_build.return_value = mock_service

            # Mock get returns existing event
            mock_service.events.return_value.get.return_value.execute.return_value = {
                "id": "google-to-cancel-123",
                "summary": "Synced Meeting",
            }

            # Mock update succeeds
            mock_service.events.return_value.update.return_value.execute.return_value = {
                "id": "google-to-cancel-123"
            }

            cancel_calendar_event(authenticated_client, test_user_id, event_id)

            # Verify Google Calendar update was called with CANCELLED title
            mock_service.events.return_value.update.assert_called_once()
            call_args = mock_service.events.return_value.update.call_args
            body = call_args.kwargs.get("body", call_args[1].get("body", {}))
            assert "CANCELLED:" in body.get("summary", "")

    def test_cancel_handles_already_deleted_google_event(
        self, authenticated_client, test_user_id
    ):
        """Test that cancelling handles case where Google event was already deleted."""
        # Create synced event with Google Calendar ID
        event_data = {
            "user_id": test_user_id,
            "title": "Already Deleted",
            "start_datetime": "2026-04-20T14:00:00Z",
            "status": "synced",
            "google_calendar_event_id": "google-already-deleted-456",
        }

        result = authenticated_client.table("events").insert(event_data).execute()
        event_id = result.data[0]["id"]

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            from googleapiclient.errors import HttpError

            mock_creds.return_value = MagicMock()

            mock_service = MagicMock()
            mock_build.return_value = mock_service

            # Mock get returns 404
            mock_resp = MagicMock()
            mock_resp.status = 404
            mock_service.events.return_value.get.return_value.execute.side_effect = HttpError(
                mock_resp, b"Not found"
            )

            # Should not raise, just log warning
            cancel_calendar_event(authenticated_client, test_user_id, event_id)

        # Verify local event was still cancelled
        updated_event = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()

        assert updated_event.data["title"] == "CANCELLED: Already Deleted"
        assert updated_event.data["status"] == "cancelled"
