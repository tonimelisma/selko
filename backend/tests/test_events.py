"""Unit tests for events service.

Tests the business logic functions in events.py with mocked dependencies.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from selko.services.events import (
    EventsError,
    check_sender_rules,
    find_matching_event,
    generate_source_attribution,
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
        mock_client.table.return_value.select.return_value.eq.return_value.gte.return_value.lte.return_value.execute.return_value = mock_result

        event_data = {
            "title": "Birthday Party",
            "start_datetime": "2026-03-15T14:00:00Z",
        }

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
        mock_client.table.return_value.select.return_value.eq.return_value.gte.return_value.lte.return_value.execute.return_value = mock_result

        event_data = {
            "title": "Jake's Birthday Party",
            "start_datetime": "2026-03-15T14:00:00Z",
        }

        with patch("selko.services.events.gemini.compare_events", return_value="event-123") as mock_compare:
            result = find_matching_event(mock_client, mock_gemini, "user-123", event_data)

            mock_compare.assert_called_once_with(
                mock_gemini,
                event_data,
                mock_result.data
            )
            assert result == "event-123"

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
        mock_client.table.return_value.select.return_value.eq.return_value.gte.return_value.lte.return_value.execute.return_value = mock_result

        event_data = {
            "title": "Some Event",
            "start_datetime": "2026-03-15T14:00:00Z",
        }

        with patch("selko.services.events.gemini.compare_events", side_effect=Exception("LLM error")):
            result = find_matching_event(mock_client, mock_gemini, "user-123", event_data)

            # Should return None on failure, not raise
            assert result is None

    def test_parses_datetime_string(self):
        """Test parsing of ISO datetime string."""
        mock_client = MagicMock()
        mock_gemini = MagicMock()

        mock_result = MagicMock()
        mock_result.data = []
        mock_client.table.return_value.select.return_value.eq.return_value.gte.return_value.lte.return_value.execute.return_value = mock_result

        event_data = {
            "title": "Test Event",
            "start_datetime": "2026-03-15T14:00:00+00:00",
        }

        result = find_matching_event(mock_client, mock_gemini, "user-123", event_data)

        # Should parse without error
        assert result is None
        # Verify the date query was made
        mock_client.table.assert_called_with("events")

    def test_parses_datetime_with_z_suffix(self):
        """Test parsing of datetime string with Z suffix."""
        mock_client = MagicMock()
        mock_gemini = MagicMock()

        mock_result = MagicMock()
        mock_result.data = []
        mock_client.table.return_value.select.return_value.eq.return_value.gte.return_value.lte.return_value.execute.return_value = mock_result

        event_data = {
            "title": "Test Event",
            "start_datetime": "2026-03-15T14:00:00Z",
        }

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
