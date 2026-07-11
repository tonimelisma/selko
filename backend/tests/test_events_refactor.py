"""Unit tests for refactored event pipeline helpers.

Tests the extracted helper functions: mark_email_status, should_skip_email,
normalize_event_data, save_extracted_events, and the slimmed-down
process_email_for_events orchestrator.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from zoneinfo import ZoneInfo

from selko.api.schemas.calendar import CalendarEvent, CalendarEventExtraction
from selko.services.events import (
    EventsError,
    create_event,
    mark_email_status,
    normalize_event_data,
    process_email_for_events,
    save_extracted_events,
    should_skip_email,
)

TEST_TIMEZONE = "America/New_York"
TEST_ZONE = ZoneInfo(TEST_TIMEZONE)
FIXED_NOW = datetime(2026, 4, 9, 12, 0, tzinfo=TEST_ZONE)


# --- Helpers for building mock objects ---


def _make_calendar_event(**overrides):
    """Build a CalendarEvent with sensible defaults.

    Default start/end are dynamically future-dated so events aren't dropped by
    the past-event filter in save_extracted_events. Tests that assert on exact
    serialized datetimes should pass explicit dates via overrides.
    """
    future = datetime.now() + timedelta(days=30)
    defaults = {
        "title": "Team Meeting",
        "start_datetime": future.replace(hour=14, minute=0, second=0, microsecond=0),
        "end_datetime": future.replace(hour=15, minute=0, second=0, microsecond=0),
        "location": "Room A",
        "description": "Weekly sync",
    }
    defaults.update(overrides)
    return CalendarEvent(**defaults)


def _make_extraction(events=None, events_found=True):
    """Build a CalendarEventExtraction."""
    return CalendarEventExtraction(
        email_message_id="msg-123",
        email_date=datetime(2026, 4, 9, 10, 0),
        sender_email="sender@example.com",
        events_found=events_found,
        events=events or [],
    )


class TestMarkEmailStatus:
    """Tests for mark_email_status helper."""

    def test_sets_processing_with_timestamp(self):
        mock_client = MagicMock()
        mark_email_status(mock_client, "email-1", "processing")

        mock_client.table.assert_called_with("emails")
        update_call = mock_client.table.return_value.update.call_args[0][0]
        assert update_call["processing_status"] == "processing"
        assert "processed_at" in update_call

    def test_sets_processed_without_timestamp(self):
        mock_client = MagicMock()
        mark_email_status(mock_client, "email-1", "processed")

        update_call = mock_client.table.return_value.update.call_args[0][0]
        assert update_call["processing_status"] == "processed"
        assert "processed_at" not in update_call

    def test_sets_skipped(self):
        mock_client = MagicMock()
        mark_email_status(mock_client, "email-1", "skipped")

        update_call = mock_client.table.return_value.update.call_args[0][0]
        assert update_call["processing_status"] == "skipped"
        assert "processing_error" not in update_call

    def test_sets_failed_with_error(self):
        mock_client = MagicMock()
        mark_email_status(mock_client, "email-1", "failed", error="LLM timeout")

        update_call = mock_client.table.return_value.update.call_args[0][0]
        assert update_call["processing_status"] == "failed"
        assert update_call["processing_error"] == "LLM timeout"


class TestShouldSkipEmail:
    """Tests for should_skip_email helper."""

    def test_returns_true_for_ignored_sender(self):
        mock_client = MagicMock()
        with patch("selko.services.events.check_sender_rules", return_value={"action": "ignore"}):
            assert should_skip_email(mock_client, "user-1", "spam@example.com") is True

    def test_returns_false_for_auto_approve_sender(self):
        mock_client = MagicMock()
        with patch("selko.services.events.check_sender_rules", return_value={"action": "auto_approve"}):
            assert should_skip_email(mock_client, "user-1", "school@example.com") is False

    def test_returns_false_when_no_rule(self):
        mock_client = MagicMock()
        with patch("selko.services.events.check_sender_rules", return_value=None):
            assert should_skip_email(mock_client, "user-1", "unknown@example.com") is False


class TestNormalizeEventData:
    """Tests for normalize_event_data helper."""

    def test_converts_all_fields(self):
        # Explicit fixed dates so the exact-ISO assertions below are stable.
        event = _make_calendar_event(
            start_datetime=datetime(2026, 3, 15, 14, 0),
            end_datetime=datetime(2026, 3, 15, 15, 0),
        )
        result = normalize_event_data(event)

        assert result["title"] == "Team Meeting"
        # Naive datetimes are localized to America/New_York (default); March 15 = EDT (-04:00)
        assert result["start_datetime"] == "2026-03-15T14:00:00-04:00"
        assert result["end_datetime"] == "2026-03-15T15:00:00-04:00"
        assert result["all_day"] is False
        assert result["location"] == "Room A"
        assert result["description"] == "Weekly sync"
        assert result["source_quote"] == ""

    def test_handles_none_datetimes(self):
        event = _make_calendar_event(start_datetime=None, end_datetime=None)
        result = normalize_event_data(event)

        assert result["start_datetime"] is None
        assert result["end_datetime"] is None

    def test_handles_missing_optional_fields(self):
        event = _make_calendar_event(location=None, description="")
        result = normalize_event_data(event)

        assert result["location"] is None
        assert result["description"] == ""


class TestSaveExtractedEvents:
    """Tests for save_extracted_events helper."""

    def test_creates_new_event_when_no_match(self):
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        extraction = _make_extraction(events=[_make_calendar_event()])

        with patch("selko.services.events.find_matching_event", return_value=None), \
             patch("selko.services.events.create_event", return_value="new-id") as mock_create:
            num_new, num_updated = save_extracted_events(
                mock_client, mock_gateway, "user-1", "email-1", extraction, current_time=FIXED_NOW
            )

        assert num_new == 1
        assert num_updated == 0
        mock_create.assert_called_once()

    def test_skips_noop_gcal_match(self):
        from selko.services.event_diff import EventChangeSet
        from selko.services.events import EventMatch

        mock_client = MagicMock()
        mock_gateway = MagicMock()
        extraction = _make_extraction(events=[_make_calendar_event()])
        match = EventMatch(
            match_id="gcal:abc-123",
            baseline={"title": "Team Meeting", "start_datetime": "2026-03-15T14:00:00Z"},
        )

        with patch("selko.services.events.find_matching_event", return_value=match), \
             patch(
                 "selko.services.events.event_processing.propose_event_update",
                 return_value=EventChangeSet(kind="noop", changes=[]),
             ), \
             patch("selko.services.events.create_pending_change_from_gcal") as mock_gcal:
            num_new, num_updated = save_extracted_events(
                mock_client, mock_gateway, "user-1", "email-1", extraction, current_time=FIXED_NOW
            )

        assert num_new == 0
        assert num_updated == 0
        mock_gcal.assert_not_called()

    def test_proposes_gcal_change_when_material(self):
        from selko.services.event_diff import EventChangeSet, FieldChange
        from selko.services.events import EventMatch

        mock_client = MagicMock()
        mock_gateway = MagicMock()
        extraction = _make_extraction(events=[_make_calendar_event()])
        match = EventMatch(
            match_id="gcal:abc-123",
            baseline={
                "title": "Team Meeting",
                "start_datetime": "2026-03-15T14:00:00Z",
                "status": "synced",
            },
        )
        change_set = EventChangeSet(
            kind="material_update",
            changes=[
                FieldChange(
                    field="start_datetime",
                    before="2026-03-15T14:00:00Z",
                    after="2026-03-15T15:00:00Z",
                )
            ],
        )

        with patch("selko.services.events.find_matching_event", return_value=match), \
             patch(
                 "selko.services.events.event_processing.propose_event_update",
                 return_value=change_set,
             ), \
             patch(
                 "selko.services.events.create_pending_change_from_gcal",
                 return_value="new-id",
             ) as mock_gcal:
            num_new, num_updated = save_extracted_events(
                mock_client, mock_gateway, "user-1", "email-1", extraction
            )

        assert num_new == 0
        assert num_updated == 1
        mock_gcal.assert_called_once()
        assert mock_gcal.call_args[0][4] == "abc-123"

    def test_proposes_local_change_when_material(self):
        from selko.services.event_diff import EventChangeSet, FieldChange
        from selko.services.events import EventMatch

        mock_client = MagicMock()
        mock_gateway = MagicMock()
        extraction = _make_extraction(events=[_make_calendar_event()])
        match = EventMatch(
            match_id="event-456",
            baseline={
                "title": "Team Meeting",
                "start_datetime": "2026-03-15T14:00:00Z",
                "status": "synced",
            },
        )
        change_set = EventChangeSet(
            kind="material_update",
            changes=[
                FieldChange(
                    field="location",
                    before="Room A",
                    after="Room B",
                )
            ],
        )

        with patch("selko.services.events.find_matching_event", return_value=match), \
             patch(
                 "selko.services.events.event_processing.propose_event_update",
                 return_value=change_set,
             ), \
             patch("selko.services.events.propose_local_change") as mock_propose:
            num_new, num_updated = save_extracted_events(
                mock_client, mock_gateway, "user-1", "email-1", extraction, current_time=FIXED_NOW
            )

        assert num_new == 0
        assert num_updated == 1
        mock_propose.assert_called_once()

    def test_handles_multiple_events(self):
        from selko.services.event_diff import EventChangeSet, FieldChange
        from selko.services.events import EventMatch

        mock_client = MagicMock()
        mock_gateway = MagicMock()
        extraction = _make_extraction(events=[
            _make_calendar_event(title="Event 1"),
            _make_calendar_event(title="Event 2"),
            _make_calendar_event(title="Event 3"),
        ])
        match = EventMatch(
            match_id="event-1",
            baseline={"title": "Event 2", "start_datetime": "2026-03-15T14:00:00Z"},
        )
        change_set = EventChangeSet(
            kind="enrichment",
            changes=[FieldChange(field="description", before="a", after="b")],
        )

        with patch(
            "selko.services.events.find_matching_event",
            side_effect=[None, match, None],
        ), \
             patch("selko.services.events.create_event", return_value="new-id"), \
             patch(
                 "selko.services.events.event_processing.propose_event_update",
                 return_value=change_set,
             ), \
             patch("selko.services.events.propose_local_change"):
            num_new, num_updated = save_extracted_events(
                mock_client, mock_gateway, "user-1", "email-1", extraction, current_time=FIXED_NOW
            )

        assert num_new == 2
        assert num_updated == 1

    def test_returns_zero_for_empty_extraction(self):
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        extraction = _make_extraction(events=[], events_found=False)

        num_new, num_updated = save_extracted_events(
            mock_client, mock_gateway, "user-1", "email-1", extraction, current_time=FIXED_NOW
        )

        assert num_new == 0
        assert num_updated == 0

    def test_counts_are_correct_with_mixed_results(self):
        from selko.services.event_diff import EventChangeSet, FieldChange
        from selko.services.events import EventMatch

        mock_client = MagicMock()
        mock_gateway = MagicMock()
        extraction = _make_extraction(events=[
            _make_calendar_event(title="New Event"),
            _make_calendar_event(title="GCal Match"),
            _make_calendar_event(title="Update Existing"),
            _make_calendar_event(title="Another New"),
        ])
        gcal_match = EventMatch(
            match_id="gcal:g1",
            baseline={"title": "GCal Match", "start_datetime": "2026-03-15T14:00:00Z"},
        )
        local_match = EventMatch(
            match_id="event-1",
            baseline={"title": "Update Existing", "start_datetime": "2026-03-15T14:00:00Z"},
        )
        change_set = EventChangeSet(
            kind="material_update",
            changes=[FieldChange(field="location", before="A", after="B")],
        )

        with patch(
            "selko.services.events.find_matching_event",
            side_effect=[None, gcal_match, local_match, None],
        ), \
             patch("selko.services.events.create_event", return_value="new-id"), \
             patch(
                 "selko.services.events.event_processing.propose_event_update",
                 return_value=change_set,
             ), \
             patch(
                 "selko.services.events.create_pending_change_from_gcal",
                 return_value="new-id",
             ), \
             patch("selko.services.events.propose_local_change"):
            num_new, num_updated = save_extracted_events(
                mock_client, mock_gateway, "user-1", "email-1", extraction, current_time=FIXED_NOW
            )

        assert num_new == 2
        assert num_updated == 2

    def test_skips_events_older_than_24_hours(self):
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        old_event = _make_calendar_event(
            title="Old Event",
            start_datetime=(FIXED_NOW - timedelta(hours=24, minutes=1)).replace(tzinfo=None),
            end_datetime=(FIXED_NOW - timedelta(hours=23, minutes=1)).replace(tzinfo=None),
        )
        extraction = _make_extraction(events=[old_event])

        with patch("selko.services.events.find_matching_event") as mock_match, \
             patch("selko.services.events.create_event") as mock_create:
            num_new, num_updated = save_extracted_events(
                mock_client, mock_gateway, "user-1", "email-1", extraction, current_time=FIXED_NOW
            )

        assert num_new == 0
        assert num_updated == 0
        mock_match.assert_not_called()
        mock_create.assert_not_called()

    def test_keeps_events_exactly_at_24_hour_cutoff(self):
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        boundary_event = _make_calendar_event(
            title="Boundary Event",
            start_datetime=(FIXED_NOW - timedelta(hours=24)).replace(tzinfo=None),
            end_datetime=(FIXED_NOW - timedelta(hours=23)).replace(tzinfo=None),
        )
        extraction = _make_extraction(events=[boundary_event])

        with patch("selko.services.events.find_matching_event", return_value=None), \
             patch("selko.services.events.create_event", return_value="new-id") as mock_create:
            num_new, num_updated = save_extracted_events(
                mock_client, mock_gateway, "user-1", "email-1", extraction, current_time=FIXED_NOW
            )

        assert num_new == 1
        assert num_updated == 0
        mock_create.assert_called_once()

    def test_keeps_timezone_aware_events_inside_cutoff_window(self):
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        aware_start = (FIXED_NOW - timedelta(hours=23)).astimezone(timezone.utc)
        aware_end = aware_start + timedelta(hours=1)
        extraction = _make_extraction(events=[
            _make_calendar_event(
                title="Aware Event",
                start_datetime=aware_start,
                end_datetime=aware_end,
            )
        ])

        with patch("selko.services.events.find_matching_event", return_value=None), \
             patch("selko.services.events.create_event", return_value="new-id") as mock_create:
            num_new, num_updated = save_extracted_events(
                mock_client, mock_gateway, "user-1", "email-1", extraction, current_time=FIXED_NOW
            )

        assert num_new == 1
        assert num_updated == 0
        mock_create.assert_called_once()

class TestProcessEmailPipeline:
    """Tests for the slimmed-down process_email_for_events orchestrator."""

    def test_happy_path_end_to_end(self):
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.for_user.return_value.for_email.return_value = mock_gateway

        extraction = _make_extraction(
            events=[_make_calendar_event()],
            events_found=True,
        )

        with patch("selko.services.events.mark_email_status") as mock_mark, \
             patch("selko.services.events.event_processing.fetch_email_with_attachments",
                   return_value=({"from_email": "sender@example.com"}, "text", [])), \
             patch("selko.services.events.check_sender_rules", return_value=None), \
             patch("selko.services.events.event_processing.extract_calendar_events",
                   return_value=extraction), \
             patch("selko.services.events.save_extracted_events", return_value=(1, 0)):
            result = process_email_for_events(
                mock_client, mock_gateway, "email-1", "user-1"
            )

        assert result["num_events"] == 1
        assert result["num_new"] == 1
        assert result["num_updated"] == 0

        # Verify status transitions: processing -> processed
        status_calls = [call[0][2] for call in mock_mark.call_args_list]
        assert status_calls == ["processing", "processed"]

    def test_sender_ignored_short_circuits(self):
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.for_user.return_value.for_email.return_value = mock_gateway

        with patch("selko.services.events.mark_email_status") as mock_mark, \
             patch("selko.services.events.event_processing.fetch_email_with_attachments",
                   return_value=({"from_email": "spam@example.com"}, "text", [])), \
             patch("selko.services.events.check_sender_rules",
                   return_value={"action": "ignore"}), \
             patch("selko.services.events.event_processing.extract_calendar_events") as mock_extract:
            result = process_email_for_events(
                mock_client, mock_gateway, "email-1", "user-1"
            )

        assert result["skipped"] is True
        assert result["num_events"] == 0
        mock_extract.assert_not_called()

        # Verify status: processing -> skipped
        status_calls = [call[0][2] for call in mock_mark.call_args_list]
        assert status_calls == ["processing", "skipped"]

    def test_no_events_short_circuits(self):
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.for_user.return_value.for_email.return_value = mock_gateway

        extraction = _make_extraction(events=[], events_found=False)

        with patch("selko.services.events.mark_email_status") as mock_mark, \
             patch("selko.services.events.event_processing.fetch_email_with_attachments",
                   return_value=({"from_email": "sender@example.com"}, "text", [])), \
             patch("selko.services.events.check_sender_rules", return_value=None), \
             patch("selko.services.events.event_processing.extract_calendar_events",
                   return_value=extraction), \
             patch("selko.services.events.save_extracted_events") as mock_save:
            result = process_email_for_events(
                mock_client, mock_gateway, "email-1", "user-1"
            )

        assert result["num_events"] == 0
        mock_save.assert_not_called()

        # Verify status: processing -> processed
        status_calls = [call[0][2] for call in mock_mark.call_args_list]
        assert status_calls == ["processing", "processed"]

    def test_exception_marks_failed(self):
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.for_user.return_value.for_email.return_value = mock_gateway

        with patch("selko.services.events.mark_email_status") as mock_mark, \
             patch("selko.services.events.event_processing.fetch_email_with_attachments",
                   side_effect=RuntimeError("DB connection lost")):
            with pytest.raises(EventsError, match="Failed to process email"):
                process_email_for_events(
                    mock_client, mock_gateway, "email-1", "user-1"
                )

        # Verify status: processing then failed with error
        assert mock_mark.call_count == 2
        fail_call = mock_mark.call_args_list[1]
        assert fail_call[0][2] == "failed"
        assert fail_call[1]["error"] == "DB connection lost"

    def test_ics_attachment_skips_llm(self):
        """When email has .ics attachment, LLM extraction is skipped."""
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.for_user.return_value.for_email.return_value = mock_gateway

        ics_data = b"""\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:ICS Event
DTSTART:20260315T140000Z
DTEND:20260315T150000Z
DESCRIPTION:From .ics
END:VEVENT
END:VCALENDAR"""

        attachments = [
            {"data": ics_data, "mime_type": "text/calendar", "filename": "invite.ics"},
        ]

        with patch("selko.services.events.mark_email_status"), \
             patch("selko.services.events.event_processing.fetch_email_with_attachments",
                   return_value=({"provider_message_id": "msg-1", "from_email": "sender@example.com",
                                  "date_sent": "2026-03-15T10:00:00Z"}, "text", attachments)), \
             patch("selko.services.events.check_sender_rules", return_value=None), \
             patch("selko.services.events.event_processing.extract_calendar_events") as mock_llm, \
             patch("selko.services.events.save_extracted_events", return_value=(1, 0)):
            result = process_email_for_events(
                mock_client, mock_gateway, "email-1", "user-1"
            )

        # LLM should NOT have been called
        mock_llm.assert_not_called()
        assert result["num_events"] == 1
        assert result["num_new"] == 1

    def test_ics_parse_failure_falls_back_to_llm(self):
        """When .ics parsing fails, falls back to LLM extraction."""
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.for_user.return_value.for_email.return_value = mock_gateway

        # Malformed .ics data
        attachments = [
            {"data": b"not valid ics", "mime_type": "text/calendar", "filename": "bad.ics"},
        ]

        extraction = _make_extraction(
            events=[_make_calendar_event()],
            events_found=True,
        )

        with patch("selko.services.events.mark_email_status"), \
             patch("selko.services.events.event_processing.fetch_email_with_attachments",
                   return_value=({"provider_message_id": "msg-1", "from_email": "sender@example.com",
                                  "date_sent": "2026-03-15T10:00:00Z"}, "text", attachments)), \
             patch("selko.services.events.check_sender_rules", return_value=None), \
             patch("selko.services.events.event_processing.extract_calendar_events",
                   return_value=extraction) as mock_llm, \
             patch("selko.services.events.save_extracted_events", return_value=(1, 0)):
            result = process_email_for_events(
                mock_client, mock_gateway, "email-1", "user-1"
            )

        # LLM SHOULD have been called as fallback
        mock_llm.assert_called_once()
        assert result["num_events"] == 1


class TestAutoApproveSenderRule:
    """Tests for auto_approve sender rule action."""

    def test_process_email_auto_approve_creates_approved_events(self):
        """When sender has auto_approve rule, save_extracted_events gets initial_status='approved'."""
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.for_user.return_value.for_email.return_value = mock_gateway

        extraction = _make_extraction(
            events=[_make_calendar_event()],
            events_found=True,
        )

        with patch("selko.services.events.mark_email_status"), \
             patch("selko.services.events.event_processing.fetch_email_with_attachments",
                   return_value=({"from_email": "school@example.com"}, "text", [])), \
             patch("selko.services.events.check_sender_rules",
                   return_value={"action": "auto_approve"}), \
             patch("selko.services.events.event_processing.extract_calendar_events",
                   return_value=extraction), \
             patch("selko.services.events.save_extracted_events",
                   return_value=(1, 0)) as mock_save:
            process_email_for_events(
                mock_client, mock_gateway, "email-1", "user-1"
            )

        # Verify save_extracted_events was called with initial_status="approved"
        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args
        assert call_kwargs[1]["initial_status"] == "approved"

    def test_process_email_auto_approve_returns_flag(self):
        """When sender has auto_approve rule, return dict includes auto_approved=True."""
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.for_user.return_value.for_email.return_value = mock_gateway

        extraction = _make_extraction(
            events=[_make_calendar_event()],
            events_found=True,
        )

        with patch("selko.services.events.mark_email_status"), \
             patch("selko.services.events.event_processing.fetch_email_with_attachments",
                   return_value=({"from_email": "school@example.com"}, "text", [])), \
             patch("selko.services.events.check_sender_rules",
                   return_value={"action": "auto_approve"}), \
             patch("selko.services.events.event_processing.extract_calendar_events",
                   return_value=extraction), \
             patch("selko.services.events.save_extracted_events", return_value=(1, 0)):
            result = process_email_for_events(
                mock_client, mock_gateway, "email-1", "user-1"
            )

        assert result["auto_approved"] is True
        assert result["num_events"] == 1
        assert result["num_new"] == 1

    def test_process_email_no_rule_creates_pending_events(self):
        """When no sender rule, save_extracted_events gets default initial_status='pending_review'."""
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        mock_gateway.for_user.return_value.for_email.return_value = mock_gateway

        extraction = _make_extraction(
            events=[_make_calendar_event()],
            events_found=True,
        )

        with patch("selko.services.events.mark_email_status"), \
             patch("selko.services.events.event_processing.fetch_email_with_attachments",
                   return_value=({"from_email": "unknown@example.com"}, "text", [])), \
             patch("selko.services.events.check_sender_rules", return_value=None), \
             patch("selko.services.events.event_processing.extract_calendar_events",
                   return_value=extraction), \
             patch("selko.services.events.save_extracted_events",
                   return_value=(1, 0)) as mock_save:
            result = process_email_for_events(
                mock_client, mock_gateway, "email-1", "user-1"
            )

        # Verify save_extracted_events was called with default initial_status
        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args
        assert call_kwargs[1]["initial_status"] == "pending_review"

        # auto_approved should NOT be in the result
        assert "auto_approved" not in result

    def test_create_event_with_initial_status(self):
        """create_event() passes initial_status to the Supabase insert call."""
        mock_client = MagicMock()
        mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "event-123"}]
        )

        with patch("selko.services.events.generate_source_attribution", return_value="From test"):
            create_event(
                mock_client, "user-1",
                {"title": "Test Event", "start_datetime": "2026-03-15T14:00:00",
                 "end_datetime": "2026-03-15T15:00:00"},
                "email-1",
                initial_status="approved",
            )

        # The first insert call is for the events table
        first_insert_data = mock_client.table.return_value.insert.call_args_list[0][0][0]
        assert first_insert_data["status"] == "approved"
        assert first_insert_data["title"] == "Test Event"


class TestPastEventFiltering:
    """Tests for past event filtering in save_extracted_events."""

    def test_filters_past_events(self):
        """Events >24h in the past are skipped, future events are saved."""
        mock_client = MagicMock()
        mock_gateway = MagicMock()

        now = datetime.now(timezone.utc)
        past_event = _make_calendar_event(
            title="Past Event",
            start_datetime=now - timedelta(hours=48),
            end_datetime=now - timedelta(hours=47),
        )
        future_event = _make_calendar_event(
            title="Future Event",
            start_datetime=now + timedelta(days=7),
            end_datetime=now + timedelta(days=7, hours=1),
        )
        extraction = _make_extraction(events=[past_event, future_event])

        with patch("selko.services.events.find_matching_event", return_value=None), \
             patch("selko.services.events.create_event", return_value="new-id") as mock_create:
            num_new, num_updated = save_extracted_events(
                mock_client, mock_gateway, "user-1", "email-1", extraction
            )

        # Only the future event should be created
        assert num_new == 1
        assert num_updated == 0
        mock_create.assert_called_once()
        created_data = mock_create.call_args[0][2]
        assert created_data["title"] == "Future Event"

    def test_keeps_recent_past_events(self):
        """Events within the 24h window are NOT filtered."""
        mock_client = MagicMock()
        mock_gateway = MagicMock()

        now = datetime.now(timezone.utc)
        recent_event = _make_calendar_event(
            title="Just Happened",
            start_datetime=now - timedelta(hours=12),
            end_datetime=now - timedelta(hours=11),
        )
        extraction = _make_extraction(events=[recent_event])

        with patch("selko.services.events.find_matching_event", return_value=None), \
             patch("selko.services.events.create_event", return_value="new-id") as mock_create:
            num_new, num_updated = save_extracted_events(
                mock_client, mock_gateway, "user-1", "email-1", extraction
            )

        assert num_new == 1
        mock_create.assert_called_once()
