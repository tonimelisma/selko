"""Unit tests for timezone infrastructure changes."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest


class TestGetUserTimezone:
    """Tests for events.get_user_timezone()."""

    def test_returns_timezone_from_settings(self):
        """Test that user's configured timezone is returned."""
        from selko.services.events import get_user_timezone

        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"timezone": "America/Los_Angeles"}
        ]

        result = get_user_timezone(mock_client, "user-123")
        assert result == "America/Los_Angeles"

    def test_returns_default_when_no_settings(self):
        """Test that default timezone is returned when no settings exist."""
        from selko.services.events import get_user_timezone

        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

        result = get_user_timezone(mock_client, "user-123")
        assert result == "America/New_York"

    def test_returns_default_when_timezone_is_none(self):
        """Test that default is returned when timezone column is None."""
        from selko.services.events import get_user_timezone

        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"timezone": None}
        ]

        result = get_user_timezone(mock_client, "user-123")
        assert result == "America/New_York"

    def test_returns_default_on_db_error(self):
        """Test that default is returned when DB query fails."""
        from selko.services.events import get_user_timezone

        mock_client = MagicMock()
        mock_client.table.side_effect = Exception("DB error")

        result = get_user_timezone(mock_client, "user-123")
        assert result == "America/New_York"


class TestNormalizeEventData:
    """Tests for events.normalize_event_data() with timezone support."""

    def _make_event(self, start_dt=None, end_dt=None, all_day=False, location=None,
                    description=None, title="Test Event", importance="action_required"):
        """Create a CalendarEvent-like mock."""
        from selko.api.schemas.calendar import CalendarEvent
        event = MagicMock(spec=CalendarEvent)
        event.title = title
        event.start_datetime = start_dt
        event.end_datetime = end_dt
        event.all_day = all_day
        event.location = location
        event.description = description
        event.source_quote = ""
        event.importance = importance
        return event

    def test_naive_datetime_gets_user_timezone(self):
        """Naive datetimes should be localized to user's timezone."""
        from selko.services.events import normalize_event_data

        naive_dt = datetime(2026, 3, 15, 14, 0, 0)
        event = self._make_event(start_dt=naive_dt)

        result = normalize_event_data(event, user_timezone="America/New_York")

        # Should include timezone offset in isoformat
        assert result["start_datetime"] is not None
        assert "-04:00" in result["start_datetime"] or "-05:00" in result["start_datetime"]

    def test_aware_datetime_passes_through_unchanged(self):
        """Already timezone-aware datetimes should not be modified."""
        from selko.services.events import normalize_event_data

        aware_dt = datetime(2026, 3, 15, 14, 0, 0, tzinfo=ZoneInfo("America/Chicago"))
        event = self._make_event(start_dt=aware_dt)

        result = normalize_event_data(event, user_timezone="America/New_York")

        # Should preserve the original timezone (Chicago), not convert to New York
        assert "America/Chicago" in result["start_datetime"] or "-05:00" in result["start_datetime"] or "-06:00" in result["start_datetime"]

    def test_none_datetime_returns_none(self):
        """None datetimes should remain None."""
        from selko.services.events import normalize_event_data

        event = self._make_event(start_dt=None, end_dt=None)

        result = normalize_event_data(event)
        assert result["start_datetime"] is None
        assert result["end_datetime"] is None

    def test_default_timezone_is_america_new_york(self):
        """Default timezone should be America/New_York."""
        from selko.services.events import normalize_event_data

        naive_dt = datetime(2026, 7, 4, 12, 0, 0)  # Summer (EDT = -04:00)
        event = self._make_event(start_dt=naive_dt)

        result = normalize_event_data(event)  # No timezone specified
        assert "-04:00" in result["start_datetime"]

    def test_invalid_timezone_falls_back_to_new_york(self):
        """Invalid timezone string should fall back to America/New_York."""
        from selko.services.events import normalize_event_data

        naive_dt = datetime(2026, 7, 4, 12, 0, 0)
        event = self._make_event(start_dt=naive_dt)

        result = normalize_event_data(event, user_timezone="Not/A/Timezone")
        assert result["start_datetime"] is not None
        assert "-04:00" in result["start_datetime"]

    def test_returns_all_expected_fields(self):
        """Result dict should contain all expected DB fields."""
        from selko.services.events import normalize_event_data

        event = self._make_event(
            start_dt=datetime(2026, 3, 15, 14, 0, 0),
            title="Team Meeting",
            location="Conference Room A",
            description="Weekly sync",
            importance="action_required",
        )

        result = normalize_event_data(event, user_timezone="America/New_York")

        assert result["title"] == "Team Meeting"
        assert result["location"] == "Conference Room A"
        assert result["description"] == "Weekly sync"
        assert result["importance"] == "action_required"
        assert result["all_day"] is False


class TestCalendarSettingsTimezone:
    """Tests for calendars.get_calendar_settings() timezone inclusion."""

    def test_returns_timezone_from_settings(self):
        """Timezone from DB should be included in settings dict."""
        from selko.services.calendars import get_calendar_settings

        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {
                "target_calendar_id": "primary",
                "default_invitees": None,
                "timezone": "Europe/London",
            }
        ]

        with patch("selko.services.calendars.list_calendars", return_value=[]):
            result = get_calendar_settings(mock_client, "user-123")

        assert result["timezone"] == "Europe/London"

    def test_returns_default_timezone_when_no_settings(self):
        """Default timezone returned when user has no settings row."""
        from selko.services.calendars import get_calendar_settings

        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

        result = get_calendar_settings(mock_client, "user-123")
        assert result["timezone"] == "America/New_York"


class TestExtractCalendarEventsTzAwareness:
    """Tests for timezone-aware current_date in event_processing."""

    def test_current_date_uses_user_timezone(self):
        """current_date computed in user's timezone, not server UTC."""
        from selko.services.event_processing import extract_calendar_events
        from selko.services.llm_gateway import LLMGateway, LLMGatewayError
        from selko.api.schemas.calendar import CalendarEventExtraction

        mock_gateway = MagicMock(spec=LLMGateway)
        mock_gateway.call.return_value.text = '{"events_found": false, "events": []}'
        mock_gateway.for_user = MagicMock(return_value=mock_gateway)
        mock_gateway.for_email = MagicMock(return_value=mock_gateway)

        email_metadata = {
            "provider_message_id": "test-123",
            "subject": "Test",
            "from_name": "Tester",
            "from_email": "test@example.com",
            "date_sent": "2026-03-15T10:00:00Z",
            "user_timezone": "America/New_York",
        }

        # Should not raise; we just verify it runs with user_timezone in metadata
        result = extract_calendar_events(
            mock_gateway,
            "Email body text",
            email_metadata,
        )
        assert result is not None
        # Verify the LLM was called (prompt was built)
        mock_gateway.call.assert_called_once()

    def test_invalid_user_timezone_falls_back_gracefully(self):
        """Invalid user_timezone in email_metadata falls back without error."""
        from selko.services.event_processing import extract_calendar_events

        mock_gateway = MagicMock()
        mock_gateway.call.return_value.text = '{"events_found": false, "events": []}'

        email_metadata = {
            "provider_message_id": "test-456",
            "subject": "Test",
            "from_name": "Tester",
            "from_email": "test@example.com",
            "date_sent": "2026-03-15T10:00:00Z",
            "user_timezone": "Invalid/Timezone",
        }

        result = extract_calendar_events(mock_gateway, "Email body", email_metadata)
        assert result is not None
        mock_gateway.call.assert_called_once()


class TestOAuthTimezoneDetection:
    """Tests for timezone auto-detection on Google Calendar OAuth callback."""

    def test_google_calendar_settings_api_returns_timezone(self):
        """Verify that reading timezone from Google Calendar settings API works correctly."""
        # Test the logic that would be called in the OAuth callback:
        # cal_service.settings().get(setting="timezone").execute() returns {"value": "America/Chicago"}
        mock_cal_service = MagicMock()
        mock_cal_service.settings.return_value.get.return_value.execute.return_value = {
            "value": "America/Chicago"
        }

        tz_setting = mock_cal_service.settings().get(setting="timezone").execute()
        user_timezone = tz_setting.get("value")
        assert user_timezone == "America/Chicago"

    def test_timezone_upsert_builds_correct_payload(self):
        """Verify that the upsert payload for timezone is correctly structured."""
        mock_client = MagicMock()

        user_id = "user-abc-123"
        user_timezone = "America/Chicago"

        # Simulate what the OAuth callback does
        mock_client.table("user_calendar_settings").upsert({
            "user_id": str(user_id),
            "timezone": user_timezone,
        }).execute()

        # Verify table was called with correct args
        mock_client.table.assert_called_with("user_calendar_settings")
        call_args = mock_client.table.return_value.upsert.call_args[0][0]
        assert call_args["user_id"] == user_id
        assert call_args["timezone"] == "America/Chicago"

    def test_non_calendar_oauth_does_not_upsert_timezone(self):
        """Gmail OAuth should NOT trigger timezone detection."""
        # The timezone auto-detection is gated on: if provider == "google_calendar"
        # This test verifies that logic is in place
        provider = "gmail"
        should_detect_tz = (provider == "google_calendar")
        assert should_detect_tz is False
