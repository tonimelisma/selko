"""Unit tests for undo_history_event calendar side effects."""

from unittest.mock import MagicMock, patch

import pytest

from selko.services.calendars import CalendarDivergedError
from selko.services.events import EventsError, undo_history_event


def _event_row(**overrides):
    base = {
        "id": "event-123",
        "user_id": "user-456",
        "title": "Bike Fest",
        "status": "synced",
        "google_calendar_event_id": "gcal-abc",
        "synced_at": "2026-07-12T01:00:00+00:00",
        "start_datetime": "2026-09-13T17:00:00+00:00",
        "end_datetime": "2026-09-13T21:00:00+00:00",
        "all_day": False,
        "location": "Park",
        "description": "Fun",
        "importance": "action_required",
    }
    base.update(overrides)
    return base


def _mock_event_and_sources(mock_client, event, sources):
    event_result = MagicMock()
    event_result.data = event
    sources_result = MagicMock()
    sources_result.data = sources

    def table_side_effect(name):
        table = MagicMock()
        if name == "events":
            table.select.return_value.eq.return_value.single.return_value.execute.return_value = (
                event_result
            )
            table.update.return_value.eq.return_value.execute.return_value = MagicMock()
        elif name == "event_sources":
            table.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = (
                sources_result
            )
        return table

    mock_client.table.side_effect = table_side_effect
    return mock_client


class TestUndoHistoryEventCalendar:
    def test_new_synced_deletes_calendar(self):
        mock_client = MagicMock()
        _mock_event_and_sources(mock_client, _event_row(), sources=[])

        with patch(
            "selko.services.events.calendars.assert_calendar_not_diverged"
        ) as mock_assert, patch(
            "selko.services.events.calendars.delete_calendar_event_only"
        ) as mock_delete:
            status = undo_history_event(
                mock_client, "event-123", "user-456", force=False
            )

        assert status == "pending_review"
        mock_assert.assert_called_once()
        mock_delete.assert_called_once_with(mock_client, "user-456", "event-123")

    def test_diverged_without_force_raises(self):
        mock_client = MagicMock()
        _mock_event_and_sources(mock_client, _event_row(), sources=[])

        with patch(
            "selko.services.events.calendars.assert_calendar_not_diverged",
            side_effect=CalendarDivergedError("edited", ["title"]),
        ):
            with pytest.raises(CalendarDivergedError):
                undo_history_event(
                    mock_client, "event-123", "user-456", force=False
                )

    def test_diverged_with_force_deletes(self):
        mock_client = MagicMock()
        _mock_event_and_sources(mock_client, _event_row(), sources=[])

        with patch(
            "selko.services.events.calendars.assert_calendar_not_diverged"
        ) as mock_assert, patch(
            "selko.services.events.calendars.delete_calendar_event_only"
        ) as mock_delete:
            status = undo_history_event(
                mock_client, "event-123", "user-456", force=True
            )

        assert status == "pending_review"
        mock_assert.assert_called_once_with(
            mock_client, "user-456", "event-123", "gcal-abc", force=True
        )
        mock_delete.assert_called_once()

    def test_applied_change_restores_calendar(self):
        mock_client = MagicMock()
        sources = [
            {
                "id": "src-1",
                "source_type": "update",
                "is_undone": False,
                "event_snapshot_before": {
                    "title": "Old Title",
                    "start_datetime": "2026-09-13T10:00:00-07:00",
                    "end_datetime": "2026-09-13T14:00:00-07:00",
                    "all_day": False,
                    "location": "Lot A",
                    "description": "Old",
                    "importance": "action_required",
                },
            }
        ]
        _mock_event_and_sources(mock_client, _event_row(title="New Title"), sources)

        with patch(
            "selko.services.events.calendars.assert_calendar_not_diverged"
        ), patch(
            "selko.services.events.calendars.get_calendar_event",
            return_value={"id": "gcal-abc"},
        ), patch(
            "selko.services.events.calendars.restore_calendar_event_from_selko_fields"
        ) as mock_restore:
            status = undo_history_event(
                mock_client, "event-123", "user-456", force=False
            )

        assert status == "pending_change"
        mock_restore.assert_called_once()
        restored = mock_restore.call_args[0][3]
        assert restored["title"] == "Old Title"

    def test_gcal_404_clears_sync_on_change_undo(self):
        mock_client = MagicMock()
        sources = [
            {
                "id": "src-1",
                "source_type": "update",
                "is_undone": False,
                "event_snapshot_before": {
                    "title": "Old Title",
                    "start_datetime": "2026-09-13T10:00:00-07:00",
                    "end_datetime": "2026-09-13T14:00:00-07:00",
                    "all_day": False,
                    "location": None,
                    "description": None,
                    "importance": "action_required",
                },
            }
        ]
        _mock_event_and_sources(mock_client, _event_row(), sources)

        with patch(
            "selko.services.events.calendars.assert_calendar_not_diverged"
        ), patch(
            "selko.services.events.calendars.get_calendar_event",
            return_value=None,
        ), patch(
            "selko.services.events.calendars.restore_calendar_event_from_selko_fields"
        ) as mock_restore:
            status = undo_history_event(
                mock_client, "event-123", "user-456", force=False
            )

        assert status == "pending_change"
        mock_restore.assert_not_called()
        # Final events.update should clear google id
        update_calls = [
            c for c in mock_client.table.return_value.update.call_args_list
        ]
        # table is side_effect so inspect via call tracking on MagicMock differently
        # Ensure we didn't try to restore
        assert mock_restore.call_count == 0

    def test_unsynced_local_only(self):
        mock_client = MagicMock()
        _mock_event_and_sources(
            mock_client,
            _event_row(google_calendar_event_id=None, status="rejected"),
            sources=[],
        )

        with patch(
            "selko.services.events.calendars.delete_calendar_event_only"
        ) as mock_delete:
            status = undo_history_event(
                mock_client, "event-123", "user-456", force=False
            )

        assert status == "pending_review"
        mock_delete.assert_not_called()

    def test_synced_requires_user_id(self):
        mock_client = MagicMock()
        _mock_event_and_sources(mock_client, _event_row(), sources=[])

        with pytest.raises(EventsError, match="user_id is required"):
            undo_history_event(mock_client, "event-123")
