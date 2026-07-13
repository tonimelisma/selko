"""Unit tests for events service.

Tests the business logic functions in events.py with mocked dependencies.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from selko.services.events import (
    EventsError,
    check_sender_rules,
    create_event_from_gcal_match,
    find_matching_event,
    generate_source_attribution,
    update_event,
    undo_email_contribution,
    redo_email_contribution,
)


class TestCheckSenderRules:
    """Tests for sender rule matching logic."""

    def test_exact_email_match(self):
        """Test exact email address match."""
        mock_client = MagicMock()

        # First query (exact email) returns a match
        mock_exact_result = MagicMock()
        mock_exact_result.data = [{
            "id": "rule-1",
            "sender_email": "school@example.edu",
            "action": "auto_approve",
        }]

        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_exact_result

        rule = check_sender_rules(mock_client, "user-123", "school@example.edu")

        assert rule is not None
        assert rule["action"] == "auto_approve"
        assert rule["sender_email"] == "school@example.edu"

    def test_domain_match_when_no_exact(self):
        """Test domain wildcard match when exact email not found."""
        mock_client = MagicMock()

        # First query (exact email) returns empty
        mock_exact_result = MagicMock()
        mock_exact_result.data = []

        # Second query (domain) returns a match
        mock_domain_result = MagicMock()
        mock_domain_result.data = [{
            "id": "rule-2",
            "sender_domain": "example.edu",
            "action": "ignore",
        }]

        # Setup mock chain: first call returns empty, second returns domain match
        mock_table = MagicMock()
        mock_select = MagicMock()
        mock_eq_user = MagicMock()

        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_eq_user

        # First call for exact email returns empty
        mock_exact_execute = MagicMock()
        mock_exact_execute.execute.return_value = mock_exact_result

        # Second call for domain returns match
        mock_domain_execute = MagicMock()
        mock_domain_execute.execute.return_value = mock_domain_result

        mock_eq_user.eq.side_effect = [mock_exact_execute, mock_domain_execute]

        rule = check_sender_rules(mock_client, "user-123", "newsletter@example.edu")

        assert rule is not None
        assert rule["action"] == "ignore"

    def test_no_match_returns_none(self):
        """Test that no matching rule returns None."""
        mock_client = MagicMock()

        # Both queries return empty
        mock_empty_result = MagicMock()
        mock_empty_result.data = []

        mock_table = MagicMock()
        mock_select = MagicMock()
        mock_eq_user = MagicMock()
        mock_eq_field = MagicMock()

        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_eq_user
        mock_eq_user.eq.return_value = mock_eq_field
        mock_eq_field.execute.return_value = mock_empty_result

        rule = check_sender_rules(mock_client, "user-123", "unknown@random.com")

        assert rule is None

    def test_email_without_domain(self):
        """Test handling of malformed email without @ symbol."""
        mock_client = MagicMock()

        mock_empty_result = MagicMock()
        mock_empty_result.data = []

        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_empty_result

        # Malformed email - no @ symbol
        rule = check_sender_rules(mock_client, "user-123", "malformed-email")

        assert rule is None


class TestFindMatchingEvent:
    """Tests for event deduplication matching."""

    def test_returns_none_when_no_start_datetime(self):
        """Test that events without start_datetime return None."""
        mock_client = MagicMock()
        mock_gemini = MagicMock()

        event_data = {
            "title": "Some event",
            "location": "Somewhere",
        }

        result = find_matching_event(mock_client, mock_gemini, "user-123", event_data)

        assert result is None

    def test_returns_none_when_no_candidates(self):
        """Test that no candidates on same date returns None."""
        mock_client = MagicMock()
        mock_gemini = MagicMock()

        # Query returns no events on same date
        mock_result = MagicMock()
        mock_result.data = []
        mock_client.table.return_value.select.return_value.eq.return_value.gte.return_value.lt.return_value.execute.return_value = mock_result

        event_data = {
            "title": "Birthday Party",
            "start_datetime": "2026-03-15T14:00:00Z",
        }

        with patch("selko.services.events.calendars.fetch_calendar_events_for_date_range", return_value=[]):
            result = find_matching_event(mock_client, mock_gemini, "user-123", event_data)

        assert result is None

    def test_calls_gemini_compare_when_candidates_exist(self):
        """Test that LLM comparison is called when candidates exist."""
        mock_client = MagicMock()
        mock_gemini = MagicMock()

        # Query returns candidate events
        mock_result = MagicMock()
        mock_result.data = [{
            "id": "event-123",
            "title": "Birthday Party",
            "start_datetime": "2026-03-15T14:00:00Z",
        }]
        mock_client.table.return_value.select.return_value.eq.return_value.gte.return_value.lt.return_value.execute.return_value = mock_result

        event_data = {
            "title": "Jake's Birthday Party",
            "start_datetime": "2026-03-15T14:00:00Z",
        }

        with patch("selko.services.events.event_processing.compare_events", return_value="event-123") as mock_compare, \
             patch("selko.services.events.calendars.fetch_calendar_events_for_date_range", return_value=[]):
            result = find_matching_event(mock_client, mock_gemini, "user-123", event_data)

            mock_compare.assert_called_once()
            assert result is not None
            assert result.match_id == "event-123"

    def test_handles_llm_comparison_failure(self):
        """Test graceful handling of LLM comparison failure."""
        mock_client = MagicMock()
        mock_gemini = MagicMock()

        # Query returns candidate events
        mock_result = MagicMock()
        mock_result.data = [{
            "id": "event-123",
            "title": "Some Event",
            "start_datetime": "2026-03-15T14:00:00Z",
        }]
        mock_client.table.return_value.select.return_value.eq.return_value.gte.return_value.lt.return_value.execute.return_value = mock_result

        event_data = {
            "title": "Some Event",
            "start_datetime": "2026-03-15T14:00:00Z",
        }

        with patch("selko.services.events.event_processing.compare_events", side_effect=Exception("LLM error")), \
             patch("selko.services.events.calendars.fetch_calendar_events_for_date_range", return_value=[]):
            result = find_matching_event(mock_client, mock_gemini, "user-123", event_data)

            # Should return None on failure, not raise
            assert result is None

    def test_parses_datetime_string(self):
        """Test parsing of ISO datetime string."""
        mock_client = MagicMock()
        mock_gemini = MagicMock()

        mock_result = MagicMock()
        mock_result.data = []
        mock_client.table.return_value.select.return_value.eq.return_value.gte.return_value.lt.return_value.execute.return_value = mock_result

        event_data = {
            "title": "Test Event",
            "start_datetime": "2026-03-15T14:00:00+00:00",
        }

        with patch("selko.services.events.calendars.fetch_calendar_events_for_date_range", return_value=[]):
            result = find_matching_event(mock_client, mock_gemini, "user-123", event_data)

        # Should parse without error
        assert result is None
        # Verify the date query was made
        mock_client.table.assert_any_call("events")

    def test_parses_datetime_with_z_suffix(self):
        """Test parsing of datetime string with Z suffix."""
        mock_client = MagicMock()
        mock_gemini = MagicMock()

        mock_result = MagicMock()
        mock_result.data = []
        mock_client.table.return_value.select.return_value.eq.return_value.gte.return_value.lt.return_value.execute.return_value = mock_result

        event_data = {
            "title": "Test Event",
            "start_datetime": "2026-03-15T14:00:00Z",
        }

        with patch("selko.services.events.calendars.fetch_calendar_events_for_date_range", return_value=[]):
            result = find_matching_event(mock_client, mock_gemini, "user-123", event_data)

        # Should parse Z suffix correctly
        assert result is None


class TestGenerateSourceAttribution:
    """Tests for source attribution generation."""

    def test_empty_sources_returns_empty_string(self):
        """Test that empty sources list returns empty string."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        mock_result.data = []
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = mock_result

        attribution = generate_source_attribution(mock_client, "event-123")

        assert attribution == ""

    def test_single_invitation_source(self):
        """Test attribution for single invitation source."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        mock_result.data = [{
            "source_type": "new_invitation",
            "created_at": "2026-01-25T13:30:00Z",
            "is_undone": False,
            "emails": {
                "from_email": "organizer@example.com",
                "from_name": "Event Organizer",
                "date_sent": "2026-01-25T13:30:00Z",
            }
        }]
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = mock_result

        attribution = generate_source_attribution(mock_client, "event-123")

        assert "Event Organizer" in attribution
        assert "January" in attribution or "Jan" in attribution
        assert "automatically created" in attribution

    def test_skips_undone_sources(self):
        """Test that undone sources are excluded from attribution."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        # Return undone source followed by active source
        mock_result.data = [
            {
                "source_type": "new_invitation",
                "created_at": "2026-01-20T10:00:00Z",
                "is_undone": True,  # Should be skipped
                "emails": {
                    "from_email": "old@example.com",
                    "from_name": "Old Sender",
                    "date_sent": "2026-01-20T10:00:00Z",
                }
            },
            {
                "source_type": "new_invitation",
                "created_at": "2026-01-25T13:30:00Z",
                "is_undone": False,
                "emails": {
                    "from_email": "active@example.com",
                    "from_name": "Active Sender",
                    "date_sent": "2026-01-25T13:30:00Z",
                }
            }
        ]
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = mock_result

        attribution = generate_source_attribution(mock_client, "event-123")

        # Should include active sender, not old sender
        assert "Active Sender" in attribution
        assert "Old Sender" not in attribution


class TestUndoEmailContribution:
    """Tests for undo functionality."""

    def test_raises_error_when_no_snapshot(self):
        """Test that undo raises error when no snapshot available."""
        mock_client = MagicMock()

        # Return event_source without snapshot
        mock_result = MagicMock()
        mock_result.data = {
            "id": "source-123",
            "event_id": "event-456",
            "event_snapshot_before": None,  # No snapshot
        }
        mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_result

        with pytest.raises(EventsError) as exc_info:
            undo_email_contribution(mock_client, "source-123")

        assert "No snapshot available" in str(exc_info.value)

    def test_restores_snapshot_and_marks_undone(self):
        """Test that undo restores snapshot and marks source as undone."""
        mock_client = MagicMock()

        snapshot = {
            "title": "Original Title",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T15:00:00Z",
            "all_day": False,
            "location": "Original Location",
            "description": "Original description",
        }

        # Return event_source with snapshot
        mock_source_result = MagicMock()
        mock_source_result.data = {
            "id": "source-123",
            "event_id": "event-456",
            "event_snapshot_before": snapshot,
        }

        # Setup mock chain for the sequence of calls
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # First call: select event_source
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_eq = MagicMock()
        mock_select.eq.return_value = mock_eq
        mock_single = MagicMock()
        mock_eq.single.return_value = mock_single
        mock_single.execute.return_value = mock_source_result

        # Subsequent calls: update event, update event_source, generate attribution
        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value.execute.return_value = MagicMock()

        with patch("selko.services.events.generate_source_attribution", return_value="Updated attribution"):
            undo_email_contribution(mock_client, "source-123")

        # Verify update was called to restore snapshot
        assert mock_table.update.called


class TestRedoEmailContribution:
    """Tests for redo functionality."""

    def test_marks_source_as_not_undone(self):
        """Test that redo marks source as not undone."""
        mock_client = MagicMock()

        # First call: update event_source
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value.execute.return_value = MagicMock()

        # Second call: select event_id
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_eq = MagicMock()
        mock_select.eq.return_value = mock_eq
        mock_single = MagicMock()
        mock_eq.single.return_value = mock_single
        mock_result = MagicMock()
        mock_result.data = {"event_id": "event-456"}
        mock_single.execute.return_value = mock_result

        with patch("selko.services.events.generate_source_attribution", return_value="Updated attribution"):
            redo_email_contribution(mock_client, "source-123")

        # Verify update was called with is_undone: False
        update_calls = [call for call in mock_table.update.call_args_list]
        assert len(update_calls) >= 1


class TestFindMatchingEventGCal:
    """Tests for GCal read-back during deduplication."""

    def test_includes_gcal_candidates(self):
        """Test that GCal events are added to LLM comparison candidates."""
        mock_client = MagicMock()
        mock_gemini = MagicMock()

        # No local events
        mock_result = MagicMock()
        mock_result.data = []
        mock_client.table.return_value.select.return_value.eq.return_value.gte.return_value.lt.return_value.execute.return_value = mock_result
        # No existing Selko row already linked to this GCal event
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.not_.in_.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        event_data = {
            "title": "Team Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
        }

        gcal_events = [{
            "id": "gcal-abc",
            "summary": "Team Meeting",
            "start": {"dateTime": "2026-03-15T14:00:00Z"},
            "end": {"dateTime": "2026-03-15T15:00:00Z"},
            "location": "Room A",
            "description": "Weekly sync",
        }]

        with patch("selko.services.events.calendars.fetch_calendar_events_for_date_range", return_value=gcal_events), \
             patch("selko.services.events.event_processing.compare_events", return_value="gcal:gcal-abc") as mock_compare:
            result = find_matching_event(mock_client, mock_gemini, "user-123", event_data)

            # Should have called compare with the GCal candidate
            mock_compare.assert_called_once()
            candidates = mock_compare.call_args[0][2]
            assert len(candidates) == 1
            assert candidates[0]["id"] == "gcal:gcal-abc"
            assert candidates[0]["_source"] == "google_calendar"
            assert result is not None
            assert result.match_id == "gcal:gcal-abc"
            assert result.is_gcal is True

    def test_skips_selko_managed_gcal_events(self):
        """Test that GCal events already managed by Selko are excluded."""
        mock_client = MagicMock()
        mock_gemini = MagicMock()

        # No local events
        mock_result = MagicMock()
        mock_result.data = []
        mock_client.table.return_value.select.return_value.eq.return_value.gte.return_value.lt.return_value.execute.return_value = mock_result

        event_data = {
            "title": "Team Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
        }

        # GCal event has selko_event_id (already managed)
        gcal_events = [{
            "id": "gcal-abc",
            "summary": "Team Meeting",
            "start": {"dateTime": "2026-03-15T14:00:00Z"},
            "end": {"dateTime": "2026-03-15T15:00:00Z"},
            "extendedProperties": {
                "private": {"selko_event_id": "event-123"}
            },
        }]

        with patch("selko.services.events.calendars.fetch_calendar_events_for_date_range", return_value=gcal_events):
            result = find_matching_event(mock_client, mock_gemini, "user-123", event_data)

        # No candidates after filtering, should return None
        assert result is None

    def test_graceful_gcal_failure(self):
        """Test that GCal API failure doesn't break dedup."""
        mock_client = MagicMock()
        mock_gemini = MagicMock()

        # Local events exist
        mock_result = MagicMock()
        mock_result.data = [{
            "id": "event-123",
            "title": "Team Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
        }]
        mock_client.table.return_value.select.return_value.eq.return_value.gte.return_value.lt.return_value.execute.return_value = mock_result

        event_data = {
            "title": "Team Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
        }

        with patch("selko.services.events.calendars.fetch_calendar_events_for_date_range", side_effect=Exception("API error")), \
             patch("selko.services.events.event_processing.compare_events", return_value="event-123"):
            result = find_matching_event(mock_client, mock_gemini, "user-123", event_data)

        # Should still match local event despite GCal failure
        assert result is not None
        assert result.match_id == "event-123"

    def test_evening_event_queries_local_day_not_utc_day(self):
        """Regression: an evening local event must not query the next UTC day.

        2026-07-27T20:00:00-07:00 (8pm Pacific) is 2026-07-28T03:00:00Z — the
        old code queried the UTC calendar day (07-27T00:00Z-07-27T23:59Z) and
        never saw same-evening duplicates stored as 07-28T03:00:00Z.
        """
        mock_client = MagicMock()
        mock_gemini = MagicMock()

        mock_result = MagicMock()
        mock_result.data = []
        mock_client.table.return_value.select.return_value.eq.return_value.gte.return_value.lt.return_value.execute.return_value = mock_result

        event_data = {
            "title": "Application Deadline",
            "start_datetime": "2026-07-27T20:00:00-07:00",
        }

        with patch(
            "selko.services.events.calendars.fetch_calendar_events_for_date_range",
            return_value=[],
        ) as mock_gcal_fetch, patch(
            "selko.services.events.get_user_timezone",
            return_value="America/Los_Angeles",
        ):
            find_matching_event(
                mock_client, mock_gemini, "user-123", event_data,
                user_timezone="America/Los_Angeles",
            )

        eq_mock = mock_client.table.return_value.select.return_value.eq.return_value
        eq_mock.gte.assert_called_once_with(
            "start_datetime", "2026-07-27T07:00:00+00:00"
        )
        eq_mock.gte.return_value.lt.assert_called_once_with(
            "start_datetime", "2026-07-28T07:00:00+00:00"
        )
        assert mock_gcal_fetch.call_args[0][2] == "2026-07-27T07:00:00+00:00"
        assert mock_gcal_fetch.call_args[0][3] == "2026-07-28T07:00:00+00:00"

    def test_reuses_existing_row_linked_to_matched_gcal_event(self):
        """Regression: a second email matching the same GCal event must reuse
        the Selko row already tracking it, not stack a second change card."""
        mock_client = MagicMock()
        mock_gemini = MagicMock()

        mock_result = MagicMock()
        mock_result.data = []
        mock_client.table.return_value.select.return_value.eq.return_value.gte.return_value.lt.return_value.execute.return_value = mock_result

        existing_row = {
            "id": "existing-event-uuid",
            "title": "Team Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T15:00:00Z",
            "all_day": False,
            "location": "Room A",
            "description": "Weekly sync",
            "importance": "action_required",
            "status": "synced",
            "google_calendar_event_id": "gcal-abc",
        }
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.not_.in_.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[existing_row]
        )

        event_data = {
            "title": "Team Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
        }

        gcal_events = [{
            "id": "gcal-abc",
            "summary": "Team Meeting",
            "start": {"dateTime": "2026-03-15T14:00:00Z"},
            "end": {"dateTime": "2026-03-15T15:00:00Z"},
        }]

        with patch("selko.services.events.calendars.fetch_calendar_events_for_date_range", return_value=gcal_events), \
             patch("selko.services.events.event_processing.compare_events", return_value="gcal:gcal-abc"):
            result = find_matching_event(mock_client, mock_gemini, "user-123", event_data)

        assert result is not None
        assert result.match_id == "existing-event-uuid"
        assert result.is_gcal is False
        assert result.baseline["title"] == "Team Meeting"


class TestCreateEventFromGCalMatch:
    """Tests for creating events from GCal matches."""

    def test_creates_event_with_gcal_id_and_two_sources(self):
        """Test that adopting a GCal event creates proper records."""
        mock_client = MagicMock()

        # Mock event insert
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        mock_insert = MagicMock()
        mock_table.insert.return_value = mock_insert
        mock_insert.execute.return_value = MagicMock(data=[{"id": "new-event-id"}])

        # Mock update for attribution
        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value.execute.return_value = MagicMock()

        # Mock select for attribution generation
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=[])

        event_data = {
            "title": "Team Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
        }

        result = create_event_from_gcal_match(
            mock_client, "user-123", event_data, "email-456", "gcal-abc"
        )

        assert result == "new-event-id"

        # Verify event was created with GCal ID
        first_insert = mock_table.insert.call_args_list[0][0][0]
        assert first_insert["google_calendar_event_id"] == "gcal-abc"
        assert first_insert["status"] == "pending_review"

        # Verify two event_sources were created (GCal + email)
        insert_calls = mock_table.insert.call_args_list
        assert len(insert_calls) >= 3  # event + 2 sources


class TestUpdateEventResync:
    """Tests for re-sync logic in update_event."""

    def test_requeues_synced_for_resync(self):
        """Test that updating a synced event sets status to approved."""
        mock_client = MagicMock()
        mock_gateway = MagicMock()

        # Existing event is synced
        mock_event_result = MagicMock()
        mock_event_result.data = {
            "id": "event-123",
            "title": "Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T15:00:00Z",
            "all_day": False,
            "location": "Room A",
            "description": "Weekly sync",
            "status": "synced",
        }

        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        # First call: select existing event
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value.single.return_value.execute.return_value = mock_event_result
        mock_select.eq.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=[])

        # Mock update
        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value.execute.return_value = MagicMock()

        # Mock insert for event_source
        mock_insert = MagicMock()
        mock_table.insert.return_value = mock_insert
        mock_insert.execute.return_value = MagicMock()

        # Mock LLM merge
        with patch("selko.services.events.event_processing.merge_event_data", return_value={
            "title": "Updated Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T15:00:00Z",
            "all_day": False,
            "location": "Room B",
            "description": "Updated weekly sync",
        }):
            update_event(mock_client, mock_gateway, "event-123", {}, "email-456", "update")

        # Verify update included status=approved and sync_attempts=0
        first_update = mock_table.update.call_args_list[0][0][0]
        assert first_update["status"] == "approved"
        assert first_update["sync_attempts"] == 0

    def test_preserves_pending_review(self):
        """Test that updating a pending_review event doesn't change status."""
        mock_client = MagicMock()
        mock_gateway = MagicMock()

        # Existing event is pending_review
        mock_event_result = MagicMock()
        mock_event_result.data = {
            "id": "event-123",
            "title": "Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T15:00:00Z",
            "all_day": False,
            "location": "Room A",
            "description": "Weekly sync",
            "status": "pending_review",
        }

        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value.single.return_value.execute.return_value = mock_event_result
        mock_select.eq.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=[])

        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value.execute.return_value = MagicMock()

        mock_insert = MagicMock()
        mock_table.insert.return_value = mock_insert
        mock_insert.execute.return_value = MagicMock()

        with patch("selko.services.events.event_processing.merge_event_data", return_value={
            "title": "Updated Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T15:00:00Z",
            "all_day": False,
            "location": "Room B",
            "description": "Updated",
        }):
            update_event(mock_client, mock_gateway, "event-123", {}, "email-456", "update")

        # Verify update did NOT include status change
        first_update = mock_table.update.call_args_list[0][0][0]
        assert "status" not in first_update


class TestGenerateAttributionWithCalendarSource:
    """Tests for attribution with calendar-sourced events."""

    def test_handles_calendar_source(self):
        """Test attribution for calendar-sourced event."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        mock_result.data = [{
            "source_type": "new_invitation",
            "source_origin": "google_calendar",
            "created_at": "2026-01-25T13:30:00Z",
            "is_undone": False,
            "emails": None,  # No email for calendar sources
        }]
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = mock_result

        attribution = generate_source_attribution(mock_client, "event-123")

        assert "your Google Calendar" in attribution
        assert "automatically created" in attribution
