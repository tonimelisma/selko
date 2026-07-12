"""Unit tests for calendar drift detection and undo helpers."""

from unittest.mock import MagicMock, patch

import pytest

from selko.services.calendars import (
    SELKO_FOOTER,
    CalendarDivergedError,
    calendar_event_diverged,
    assert_calendar_not_diverged,
    delete_calendar_event_only,
)


class TestCalendarEventDiverged:
    def _snapshot(self, **overrides):
        base = {
            "summary": "Bike Fest",
            "location": "Park",
            "description": f"Fun day{SELKO_FOOTER}",
            "start": {"dateTime": "2026-09-13T10:00:00", "timeZone": "America/Los_Angeles"},
            "end": {"dateTime": "2026-09-13T14:00:00", "timeZone": "America/Los_Angeles"},
        }
        base.update(overrides)
        return base

    def test_equal_not_diverged(self):
        snap = self._snapshot()
        live = dict(snap)
        diverged, fields = calendar_event_diverged(live, snap)
        assert diverged is False
        assert fields == []

    def test_title_change_diverged(self):
        snap = self._snapshot()
        live = self._snapshot(summary="Bike Fest EDITED")
        diverged, fields = calendar_event_diverged(live, snap)
        assert diverged is True
        assert "title" in fields

    def test_time_change_diverged(self):
        snap = self._snapshot()
        live = self._snapshot(
            start={"dateTime": "2026-09-13T11:00:00", "timeZone": "America/Los_Angeles"}
        )
        diverged, fields = calendar_event_diverged(live, snap)
        assert diverged is True
        assert "start" in fields

    def test_footer_only_description_not_diverged(self):
        snap = self._snapshot(description=f"Fun day{SELKO_FOOTER}")
        # Live GCal sometimes reorders whitespace around footer
        live = self._snapshot(description=f"Fun day\n\n{SELKO_FOOTER.strip()}")
        diverged, fields = calendar_event_diverged(live, snap)
        assert diverged is False
        assert fields == []

    def test_all_day_compare(self):
        snap = {
            "summary": "Holiday",
            "location": "",
            "description": "",
            "start": {"date": "2026-12-25"},
            "end": {"date": "2026-12-26"},
        }
        live = dict(snap)
        diverged, _ = calendar_event_diverged(live, snap)
        assert diverged is False
        live["end"] = {"date": "2026-12-27"}
        diverged, fields = calendar_event_diverged(live, snap)
        assert diverged is True
        assert "end" in fields


class TestAssertCalendarNotDiverged:
    def test_force_skips_check(self):
        mock_client = MagicMock()
        # Should not raise even with no mocks for get
        assert_calendar_not_diverged(
            mock_client, "user-1", "event-1", "gcal-1", force=True
        )

    def test_missing_snapshot_requires_force(self):
        mock_client = MagicMock()
        with patch(
            "selko.services.calendars.get_calendar_event",
            return_value={"summary": "X"},
        ), patch(
            "selko.services.calendars.get_latest_sync_snapshot",
            return_value=None,
        ):
            with pytest.raises(CalendarDivergedError) as exc:
                assert_calendar_not_diverged(
                    mock_client, "user-1", "event-1", "gcal-1", force=False
                )
            assert "unknown" in exc.value.changed_fields

    def test_matching_snapshot_ok(self):
        snap = {
            "summary": "Meeting",
            "location": "",
            "description": "",
            "start": {"dateTime": "2026-01-01T10:00:00+00:00"},
            "end": {"dateTime": "2026-01-01T11:00:00+00:00"},
        }
        mock_client = MagicMock()
        with patch(
            "selko.services.calendars.get_calendar_event",
            return_value=dict(snap),
        ), patch(
            "selko.services.calendars.get_latest_sync_snapshot",
            return_value=snap,
        ):
            assert_calendar_not_diverged(
                mock_client, "user-1", "event-1", "gcal-1", force=False
            )


class TestDeleteCalendarEventOnly:
    def test_clears_sync_fields_without_status(self):
        mock_client = MagicMock()
        mock_event_result = MagicMock()
        mock_event_result.data = {
            "id": "event-123",
            "google_calendar_event_id": "google-event-abc",
        }

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build, \
             patch("selko.services.calendars.get_calendar_settings") as mock_settings:

            mock_creds.return_value = MagicMock()
            mock_settings.return_value = {
                "target_calendar_id": "primary",
                "default_invitees": None,
                "timezone": "America/New_York",
            }
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.delete.return_value.execute.return_value = None

            mock_table = MagicMock()
            mock_client.table.return_value = mock_table
            mock_table.select.return_value.eq.return_value.single.return_value.execute.return_value = (
                mock_event_result
            )
            mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
            mock_table.insert.return_value.execute.return_value = MagicMock()

            delete_calendar_event_only(mock_client, "user-456", "event-123")

            update_data = mock_table.update.call_args_list[0][0][0]
            assert update_data["google_calendar_event_id"] is None
            assert update_data["synced_at"] is None
            assert "status" not in update_data
