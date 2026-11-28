"""Unit tests for calendars service.

The calendar sync and settings functions run on a real SQLite database (the
`db`/`factory` fixtures); only Google Calendar's API and the OAuth credential
lookup are mocked.
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from selko.services.calendars import (
    CalendarAuthRequiredError,
    CalendarsError,
    _build_calendar_event_body,
    classify_calendar_error,
    fetch_calendar_events_for_date_range,
    get_calendar_settings,
    list_calendars,
    refresh_waiting_calendar_recoveries,
    requeue_calendar_recovery_batch,
    sync_event_to_calendar,
    cancel_event_to_calendar,
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


@pytest.fixture
def user(factory):
    """A user with a connected Google Calendar (the default write target)."""
    user_id = factory.user()
    factory.integration(user_id, provider="google_calendar", scopes=["calendar"])
    return user_id


def _event(factory, user_id, **extra):
    values = {
        "title": "Test Meeting",
        "start_datetime": "2026-03-15T14:00:00.000000Z",
        "end_datetime": "2026-03-15T15:00:00.000000Z",
        "all_day": False,
        "review_status": "active",
    }
    values.update(extra)
    return factory.event(user_id, **values)


def _sync_log(db, event_id):
    return [
        db.schema.decode("calendar_sync_log", row)
        for row in db.query(
            "SELECT * FROM calendar_sync_log WHERE event_id = ? ORDER BY rowid", (event_id,)
        )
    ]


def _settings(db, user_id, **fields):
    from selko.db import integrations as db_integrations

    db_integrations.upsert_calendar_settings(db, user_id, fields)


class TestGetCalendarSettings:
    """Tests for retrieving calendar settings."""

    # Validates: SEL-391
    def test_returns_defaults_when_no_settings(self, db, user):
        """Test that defaults are returned when user has no settings."""
        settings = get_calendar_settings(db, user)

        assert settings["target_calendar_id"] is None
        assert settings["target_calendar_name"] is None
        assert settings["default_invitees"] is None
        assert settings["all_day_display_mode"] == "all_day"
        assert settings["all_day_custom_start"] is None
        assert settings["all_day_custom_end"] is None

    def test_returns_stored_settings(self, db, user):
        """Test that stored settings are returned."""
        _settings(db, user, target_calendar_id="calendar-456",
                  default_invitees="spouse@example.com")

        with patch("selko.services.calendars.list_calendars") as mock_list:
            mock_list.return_value = [
                {"id": "calendar-456", "name": "Family", "is_primary": False}
            ]
            settings = get_calendar_settings(db, user)

        assert settings["target_calendar_id"] == "calendar-456"
        assert settings["target_calendar_name"] == "Family"
        assert settings["default_invitees"] == "spouse@example.com"

    # Validates: SEL-391
    def test_reads_only_the_callers_settings(self, db, factory, user):
        other = factory.user()
        _settings(db, other, target_calendar_id="theirs", timezone="Europe/Helsinki")

        settings = get_calendar_settings(db, user, include_name=False)

        assert settings["target_calendar_id"] is None
        assert settings["timezone"] == "America/New_York"




class TestGetAllDayPolicyAndTimezone:
    def test_reads_the_stored_policy(self, db, user):
        from selko.services.calendars import get_all_day_policy_and_timezone

        _settings(db, user, timezone="Europe/Helsinki", all_day_display_mode="day_9_to_5")

        policy, tz = get_all_day_policy_and_timezone(db, user)

        assert tz == "Europe/Helsinki"
        assert policy.mode.value == "day_9_to_5"

    # Validates: SEL-391
    def test_defaults_without_a_row(self, db, user):
        from selko.services.calendars import get_all_day_policy_and_timezone

        policy, tz = get_all_day_policy_and_timezone(db, user)

        assert tz == "America/New_York"
        assert policy.mode.value == "all_day"


class TestListCalendars:
    """Tests for listing Google calendars."""

    def test_returns_calendars_with_selection_state(self, db, user):
        """Test that calendars are returned with selection state."""
        _settings(db, user, target_calendar_id="cal-2")

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()

            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.calendarList.return_value.list.return_value.execute.return_value = {
                "items": [
                    {"id": "cal-1", "summary": "Primary", "primary": True},
                    {"id": "cal-2", "summary": "Work", "primary": False},
                ]
            }

            calendars = list_calendars(db, user)

            assert len(calendars) == 2
            assert calendars[0]["id"] == "cal-1"
            assert calendars[0]["is_primary"] is True
            assert calendars[0]["is_selected"] is False
            assert calendars[1]["id"] == "cal-2"
            assert calendars[1]["is_selected"] is True

    def test_raises_error_when_no_credentials(self, db, user):
        """Test that error is raised when no credentials found."""
        with patch("selko.services.calendars.get_credentials") as mock_creds:
            mock_creds.return_value = None

            with pytest.raises(CalendarsError) as exc_info:
                list_calendars(db, user)

            assert "No Google Calendar credentials found" in str(exc_info.value)

    # Validates: SEL-352
    def test_provider_401_marks_calendar_integration_expired(self, db, user):
        """Calendar-list token rejection must trigger reconnect UI state."""
        from googleapiclient.errors import HttpError

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
            list_calendars(db, user)

        update_status.assert_called_once_with(
            db,
            "google_calendar",
            "expired",
            user_id=user,
        )


class TestSyncEventToCalendar:
    """Tests for syncing events to Google Calendar."""

    def test_creates_new_calendar_event(self, db, factory, user):
        """Test creating a new calendar event."""
        event_id = _event(factory, user)

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.list.return_value.execute.return_value = {"items": []}
            mock_service.events.return_value.insert.return_value.execute.return_value = {
                "id": "google-event-abc123"
            }

            result = sync_event_to_calendar(db, user, event_id)

            assert result == "google-event-abc123"
            mock_service.events.return_value.insert.assert_called_once()
            body = mock_service.events.return_value.insert.call_args.kwargs["body"]
            assert body["summary"] == "Test Meeting"
            assert body["extendedProperties"]["private"]["selko_event_id"] == event_id

        log = _sync_log(db, event_id)
        assert [(r["action"], r["google_calendar_event_id"], r["user_id"]) for r in log] == [
            ("created", "google-event-abc123", user)
        ]
        assert log[0]["snapshot_synced"]["summary"] == "Test Meeting"

    # Validates: SEL-333
    def test_recovers_existing_event_before_retry_insert(self, db, factory, user):
        """An ambiguous earlier insert must not create a duplicate on retry."""
        event_id = _event(factory, user)

        with (
            patch(
                "selko.services.calendars.get_credentials",
                return_value=MagicMock(),
            ),
            patch("selko.services.calendars.build") as mock_build,
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

            result = sync_event_to_calendar(db, user, event_id)

        assert result == "google-recovered-123"
        mock_service.events.return_value.list.assert_called_once_with(
            calendarId="primary",
            privateExtendedProperty=f"selko_event_id={event_id}",
            showDeleted=False,
            maxResults=2,
        )
        mock_service.events.return_value.insert.assert_not_called()
        mock_service.events.return_value.update.assert_called_once()
        assert [r["action"] for r in _sync_log(db, event_id)] == ["updated"]

    # Validates: SEL-332
    def test_updates_existing_calendar_event(self, db, factory, user):
        """Test updating an existing calendar event."""
        event_id = _event(
            factory, user, title="Updated Meeting", location="New Room",
            end_datetime="2026-03-15T16:00:00.000000Z",
            google_calendar_event_id="google-existing-123",
        )

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.get.return_value.execute.return_value = {
                "id": "google-existing-123",
                "summary": "Old Title",
            }
            mock_service.events.return_value.update.return_value.execute.return_value = {
                "id": "google-existing-123"
            }

            result = sync_event_to_calendar(db, user, event_id)

            assert result == "google-existing-123"
            mock_service.events.return_value.update.assert_called_once()
            body = mock_service.events.return_value.update.call_args.kwargs["body"]
            assert body["summary"] == "Updated Meeting"
            assert body["location"] == "New Room"

    # Validates: SEL-332
    def test_recreates_deleted_calendar_event(self, db, factory, user):
        """Test that deleted calendar events are recreated."""
        from googleapiclient.errors import HttpError

        event_id = _event(factory, user, google_calendar_event_id="google-deleted-123")

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
                "id": "google-new-456"
            }

            result = sync_event_to_calendar(db, user, event_id)

            assert result == "google-new-456"
            mock_service.events.return_value.insert.assert_called_once()
        assert [r["action"] for r in _sync_log(db, event_id)] == ["created"]

    # Validates: SEL-331
    def test_failure_leaves_event_and_log_untouched(self, db, factory, user):
        """A failed write changes nothing locally: the worker's fenced call owns failure state."""
        event_id = _event(factory, user)
        before = factory.row("events", event_id)

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.list.return_value.execute.return_value = {"items": []}
            mock_service.events.return_value.insert.return_value.execute.side_effect = Exception(
                "API Error"
            )

            with pytest.raises(CalendarsError):
                sync_event_to_calendar(db, user, event_id)

        assert factory.row("events", event_id) == before
        assert _sync_log(db, event_id) == []

    def test_refuses_another_users_event(self, db, factory, user):
        other = factory.user()
        event_id = _event(factory, other)

        with patch("selko.services.calendars.get_credentials", return_value=MagicMock()), \
             patch("selko.services.calendars.build") as mock_build:
            with pytest.raises(CalendarsError):
                sync_event_to_calendar(db, user, event_id)

        mock_build.return_value.events.return_value.insert.assert_not_called()

    # Validates: SEL-352
    def test_provider_401_marks_calendar_integration_expired(self, db, factory, user):
        """A direct Google API token rejection must trigger reconnect UI state."""
        from googleapiclient.errors import HttpError

        event_id = _event(factory, user)
        mock_response = MagicMock(status=401, reason="Unauthorized")

        with (
            patch("selko.services.calendars.get_credentials", return_value=MagicMock()),
            patch("selko.services.calendars.build") as build,
            patch(
                "selko.services.calendars.update_integration_status"
            ) as update_status,
            pytest.raises(CalendarsError),
        ):
            build.return_value.events.return_value.list.return_value.execute.return_value = {"items": []}
            build.return_value.events.return_value.insert.return_value.execute.side_effect = HttpError(
                mock_response, b"Unauthorized"
            )
            sync_event_to_calendar(db, user, event_id)

        update_status.assert_called_once_with(
            db,
            "google_calendar",
            "expired",
            user_id=user,
        )


class TestCancelEventToCalendar:
    """The worker-owned cancellation write (replaces the removed inline cancellation)."""

    # Validates: SEL-334, SEL-335
    def test_prefixes_title_with_cancelled_once(self, db, factory, user):
        event_id = _event(factory, user, title="Meeting", google_calendar_event_id="g-1")

        with patch("selko.services.calendars.get_credentials", return_value=MagicMock()), \
             patch("selko.services.calendars.build") as mock_build:
            service = mock_build.return_value
            service.events.return_value.get.return_value.execute.return_value = {
                "id": "g-1", "summary": "Meeting", "etag": "e1",
            }
            cancel_event_to_calendar(db, user, event_id)
            body = service.events.return_value.update.call_args.kwargs["body"]
            assert body["summary"] == "CANCELLED: Meeting"

            service.events.return_value.get.return_value.execute.return_value = {
                "id": "g-1", "summary": "CANCELLED: Meeting", "etag": "e2",
            }
            _set_title(db, event_id, "CANCELLED: Meeting")
            cancel_event_to_calendar(db, user, event_id)
            body = service.events.return_value.update.call_args.kwargs["body"]
            assert body["summary"] == "CANCELLED: Meeting"

        # Each cancellation's audit row is kept. Postgres's action domain lacked
        # 'cancelled', so every one was refused and the error swallowed.
        assert [r["action"] for r in _sync_log(db, event_id)] == ["cancelled", "cancelled"]

    # Validates: SEL-334, SEL-335
    def test_delete_remote_deletes_and_logs(self, db, factory, user):
        event_id = _event(factory, user, google_calendar_event_id="g-2")

        with patch("selko.services.calendars.get_credentials", return_value=MagicMock()), \
             patch("selko.services.calendars.build") as mock_build:
            service = mock_build.return_value
            service.events.return_value.get.return_value.execute.return_value = {"id": "g-2"}
            cancel_event_to_calendar(db, user, event_id, delete_remote=True)
            service.events.return_value.delete.assert_called_once()

        log = _sync_log(db, event_id)
        assert [r["action"] for r in log] == ["deleted"]
        assert log[0]["snapshot_synced"] == {"deleted_google_event_id": "g-2"}

    # Validates: SEL-334
    def test_local_only_event_touches_no_calendar(self, db, factory, user):
        event_id = _event(factory, user)

        with patch("selko.services.calendars.build") as mock_build:
            cancel_event_to_calendar(db, user, event_id)

        mock_build.assert_not_called()
        assert _sync_log(db, event_id) == []


def _set_title(db, event_id, title):
    with db.write() as tx:
        tx.execute("UPDATE events SET title = ? WHERE id = ?", (title, event_id))


class TestFetchCalendarEventsForDateRange:
    """Tests for Google Calendar read-back."""

    def test_fetches_events_successfully(self, db, user):
        """Test successful GCal events fetch."""
        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()

            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.list.return_value.execute.return_value = {
                "items": [
                    {"id": "gcal-1", "summary": "Meeting"},
                    {"id": "gcal-2", "summary": "Lunch"},
                ]
            }

            result = fetch_calendar_events_for_date_range(
                db, user,
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

    def test_reads_the_stored_target_calendar_and_timezone(self, db, user):
        _settings(db, user, target_calendar_id="family@group", timezone="Europe/Helsinki")

        with patch("selko.services.calendars.get_credentials", return_value=MagicMock()), \
             patch("selko.services.calendars.build") as mock_build:
            mock_build.return_value.events.return_value.list.return_value.execute.return_value = {"items": []}
            fetch_calendar_events_for_date_range(db, user, "a", "b")

        kwargs = mock_build.return_value.events.return_value.list.call_args.kwargs
        assert kwargs["calendarId"] == "family@group"
        assert kwargs["timeZone"] == "Europe/Helsinki"

    def test_returns_empty_no_credentials(self, db, user):
        """Test that missing credentials return empty list."""
        with patch("selko.services.calendars.get_credentials") as mock_creds:
            mock_creds.return_value = None

            result = fetch_calendar_events_for_date_range(
                db, user,
                "2026-03-15T00:00:00Z", "2026-03-15T23:59:59Z"
            )

        assert result == []

    def test_returns_empty_on_api_error(self, db, user):
        """Test that API errors return empty list (non-fatal)."""
        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()

            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.list.return_value.execute.side_effect = Exception("API error")

            result = fetch_calendar_events_for_date_range(
                db, user,
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

    # Validates: SEL-350
    def test_http_401_is_oauth_required_and_isolated_from_circuit(self):
        result = classify_calendar_error(_http_error(401))
        assert result.code == "oauth_required"
        assert result.counts_toward_circuit_breaker is False

    # Validates: SEL-350
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

    # Validates: SEL-350
    def test_http_429_is_rate_limited_and_counts_toward_circuit_breaker(self):
        result = classify_calendar_error(_http_error(429))
        assert result.code == "rate_limited"
        assert result.retryable is True
        assert result.counts_toward_circuit_breaker is True

    def test_http_503_is_provider_transient_and_counts_toward_circuit_breaker(self):
        result = classify_calendar_error(_http_error(503))
        assert result.code == "provider_transient"
        assert result.counts_toward_circuit_breaker is True

    # Validates: SEL-350
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

    # Validates: SEL-352
    def test_marks_integration_expired_and_tags_event_without_dead_lettering(self, db, factory, user):
        event_id = _event(factory, user)
        before = factory.row("events", event_id)

        with (
            patch("selko.services.calendars.get_credentials", return_value=MagicMock()),
            patch("selko.services.calendars.build") as build,
            patch(
                "selko.services.calendars.update_integration_status"
            ) as update_status,
            pytest.raises(CalendarsError) as exc_info,
        ):
            build.return_value.events.return_value.list.return_value.execute.return_value = {"items": []}
            build.return_value.events.return_value.insert.return_value.execute.side_effect = (
                _http_error(403, reason="insufficientPermissions")
            )
            sync_event_to_calendar(db, user, event_id)

        assert exc_info.value.classification.code == "oauth_scope_required"
        update_status.assert_called_once_with(
            db,
            "google_calendar",
            "expired",
            user_id=user,
        )
        # The worker's fenced calendar-work call owns local failure state;
        # this provider adapter only expires the integration capability.
        assert factory.row("events", event_id) == before


def _blocked_item(db, factory, user_id):
    from selko.db.codec import new_id

    event_id = factory.event(user_id, review_status="active")
    factory._insert("calendar_work_items", {
        "id": new_id(), "event_id": event_id, "user_id": user_id, "action": "upsert",
        "generation": 1, "status": "failed", "desired_event": {"title": "x"},
        "failure_code": "oauth_required",
    })
    return event_id


class TestRequeueCalendarRecoveryBatch:
    """Database wrapper for the calendar recovery worker's tagging step."""

    def test_tags_the_claimed_recoverys_blocked_events(self, db, factory):
        import asyncio

        from selko.db import recovery as db_recovery

        user_id = factory.user()
        event_id = _blocked_item(db, factory, user_id)
        db_recovery.complete_integration_reauthorization(
            db, user_id, "google_calendar", access_token="a", scopes=["calendar"]
        )
        claimed = db_recovery.claim_integration_recovery(db, "worker-1", lock_seconds=120)

        result = asyncio.run(requeue_calendar_recovery_batch(
            db, claimed["id"], "worker-1", batch_size=50
        ))

        assert result == 1
        assert factory.row("events", event_id)["recovery_id"] == claimed["id"]

    def test_lost_claim_returns_minus_one(self, db, factory):
        import asyncio

        assert asyncio.run(requeue_calendar_recovery_batch(db, "no-such", "worker-1")) == -1

    def test_wraps_database_failure(self, db):
        import asyncio

        with pytest.raises(CalendarsError):
            asyncio.run(requeue_calendar_recovery_batch(db, "recovery-1", "worker-1", batch_size=-1))


class TestRefreshWaitingCalendarRecoveries:
    """Database wrapper for the calendar recovery worker's completion-check step."""

    def test_finalizes_a_drained_waiting_recovery(self, db, factory):
        import asyncio

        from selko.db import recovery as db_recovery

        user_id = factory.user()
        db_recovery.complete_integration_reauthorization(
            db, user_id, "google_calendar", access_token="a", scopes=["calendar"]
        )
        claimed = db_recovery.claim_integration_recovery(db, "worker-1", lock_seconds=120)
        asyncio.run(requeue_calendar_recovery_batch(db, claimed["id"], "worker-1"))

        result = asyncio.run(refresh_waiting_calendar_recoveries(db, batch_size=10))

        assert result == 1
        assert factory.row("integration_recoveries", claimed["id"])["status"] == "completed"

    def test_zero_when_nothing_is_waiting(self, db):
        import asyncio

        assert asyncio.run(refresh_waiting_calendar_recoveries(db)) == 0

    def test_wraps_database_failure(self, db):
        import asyncio

        with pytest.raises(CalendarsError):
            asyncio.run(refresh_waiting_calendar_recoveries(db, batch_size=-1))


class TestCalendarsRoute:
    """GET /calendars through the real dependencies and database; Google mocked."""

    @pytest.fixture
    def client(self, db):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from selko.api.deps import get_current_user
        from selko.api.routes import calendars as calendars_route
        from selko.db.runtime import use_database

        app = FastAPI()
        app.include_router(calendars_route.router)
        state = {}
        app.dependency_overrides[get_current_user] = lambda: state["user"]
        use_database(db)
        try:
            with TestClient(app) as test_client:
                test_client.user_state = state
                yield test_client
        finally:
            use_database(None)

    @staticmethod
    def _as(client, user_id):
        from selko.api.deps import CurrentUser

        client.user_state["user"] = CurrentUser(id=user_id, email=None, token="t")

    # Validates: SEL-392
    def test_lists_the_callers_calendars_with_their_selection(self, db, client, user):
        _settings(db, user, target_calendar_id="cal-2")
        self._as(client, user)

        with patch("selko.services.calendars.get_credentials", return_value=MagicMock()) as creds, \
                patch("selko.services.calendars.build") as mock_build:
            mock_build.return_value.calendarList.return_value.list.return_value.execute.return_value = {
                "items": [
                    {"id": "cal-1", "summary": "Primary", "primary": True},
                    {"id": "cal-2", "summary": "Work", "primary": False},
                ]
            }
            response = client.get("/calendars")

        assert response.status_code == 200
        assert response.json() == [
            {"id": "cal-1", "name": "Primary", "is_primary": True, "is_selected": False,
             "provider": "google_calendar"},
            {"id": "cal-2", "name": "Work", "is_primary": False, "is_selected": True,
             "provider": "google_calendar"},
        ]
        assert creds.call_args.args[0] is db
        assert creds.call_args.args[1] == user

    # Validates: SEL-392
    def test_no_calendar_connection_is_404(self, db, factory, client):
        self._as(client, factory.user())

        with patch("selko.services.calendars.get_credentials", return_value=None):
            response = client.get("/calendars")

        assert response.status_code == 404
