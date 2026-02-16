"""Unit tests for refactored event pipeline helpers.

Tests the extracted helper functions: mark_email_status, should_skip_email,
normalize_event_data, save_extracted_events, and the slimmed-down
process_email_for_events orchestrator.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from selko.api.schemas.calendar import CalendarEvent, CalendarEventExtraction
from selko.services.events import (
    EventsError,
    mark_email_status,
    normalize_event_data,
    process_email_for_events,
    save_extracted_events,
    should_skip_email,
)


# --- Helpers for building mock objects ---


def _make_calendar_event(**overrides):
    """Build a CalendarEvent with sensible defaults."""
    defaults = {
        "title": "Team Meeting",
        "start_datetime": datetime(2026, 3, 15, 14, 0),
        "end_datetime": datetime(2026, 3, 15, 15, 0),
        "location": "Room A",
        "description": "Weekly sync",
        "confidence": 0.9,
    }
    defaults.update(overrides)
    return CalendarEvent(**defaults)


def _make_extraction(events=None, events_found=True):
    """Build a CalendarEventExtraction."""
    return CalendarEventExtraction(
        email_message_id="msg-123",
        email_date=datetime(2026, 3, 15, 10, 0),
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
        event = _make_calendar_event()
        result = normalize_event_data(event)

        assert result["title"] == "Team Meeting"
        assert result["start_datetime"] == "2026-03-15T14:00:00"
        assert result["end_datetime"] == "2026-03-15T15:00:00"
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
                mock_client, mock_gateway, "user-1", "email-1", extraction
            )

        assert num_new == 1
        assert num_updated == 0
        mock_create.assert_called_once()

    def test_adopts_gcal_match(self):
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        extraction = _make_extraction(events=[_make_calendar_event()])

        with patch("selko.services.events.find_matching_event", return_value="gcal:abc-123"), \
             patch("selko.services.events.create_event_from_gcal_match", return_value="new-id") as mock_gcal:
            num_new, num_updated = save_extracted_events(
                mock_client, mock_gateway, "user-1", "email-1", extraction
            )

        assert num_new == 1
        assert num_updated == 0
        mock_gcal.assert_called_once()
        # Verify gcal_id was extracted correctly
        assert mock_gcal.call_args[0][4] == "abc-123"

    def test_updates_existing_event(self):
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        extraction = _make_extraction(events=[_make_calendar_event()])

        with patch("selko.services.events.find_matching_event", return_value="event-456"), \
             patch("selko.services.events.update_event") as mock_update:
            num_new, num_updated = save_extracted_events(
                mock_client, mock_gateway, "user-1", "email-1", extraction
            )

        assert num_new == 0
        assert num_updated == 1
        mock_update.assert_called_once()

    def test_handles_multiple_events(self):
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        extraction = _make_extraction(events=[
            _make_calendar_event(title="Event 1"),
            _make_calendar_event(title="Event 2"),
            _make_calendar_event(title="Event 3"),
        ])

        with patch("selko.services.events.find_matching_event", side_effect=[None, "event-1", None]), \
             patch("selko.services.events.create_event", return_value="new-id"), \
             patch("selko.services.events.update_event"):
            num_new, num_updated = save_extracted_events(
                mock_client, mock_gateway, "user-1", "email-1", extraction
            )

        assert num_new == 2
        assert num_updated == 1

    def test_returns_zero_for_empty_extraction(self):
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        extraction = _make_extraction(events=[], events_found=False)

        num_new, num_updated = save_extracted_events(
            mock_client, mock_gateway, "user-1", "email-1", extraction
        )

        assert num_new == 0
        assert num_updated == 0

    def test_counts_are_correct_with_mixed_results(self):
        mock_client = MagicMock()
        mock_gateway = MagicMock()
        extraction = _make_extraction(events=[
            _make_calendar_event(title="New Event"),
            _make_calendar_event(title="GCal Match"),
            _make_calendar_event(title="Update Existing"),
            _make_calendar_event(title="Another New"),
        ])

        with patch("selko.services.events.find_matching_event",
                    side_effect=[None, "gcal:g1", "event-1", None]), \
             patch("selko.services.events.create_event", return_value="new-id"), \
             patch("selko.services.events.create_event_from_gcal_match", return_value="new-id"), \
             patch("selko.services.events.update_event"):
            num_new, num_updated = save_extracted_events(
                mock_client, mock_gateway, "user-1", "email-1", extraction
            )

        assert num_new == 3  # 1 new + 1 gcal + 1 new
        assert num_updated == 1


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
             patch("selko.services.events.should_skip_email", return_value=False), \
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
             patch("selko.services.events.should_skip_email", return_value=True), \
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
             patch("selko.services.events.should_skip_email", return_value=False), \
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
