"""Unit tests for calendar drift detection and undo helpers."""

from unittest.mock import MagicMock, patch

import pytest

from selko.services.calendars import (
    SELKO_FOOTER,
    CalendarDivergedError,
    calendar_event_diverged,
    assert_calendar_not_diverged,
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

    def test_equivalent_offset_and_named_timezone_not_diverged(self):
        """Google's explicit UTC offset is equivalent to Selko's IANA zone."""
        snap = self._snapshot(
            start={
                "dateTime": "2026-08-30T11:00:00",
                "timeZone": "America/Los_Angeles",
            },
            end={
                "dateTime": "2026-08-30T13:00:00",
                "timeZone": "America/Los_Angeles",
            },
        )
        live = self._snapshot(
            start={
                "dateTime": "2026-08-30T11:00:00-07:00",
                "timeZone": "America/Los_Angeles",
            },
            end={
                "dateTime": "2026-08-30T13:00:00-07:00",
                "timeZone": "America/Los_Angeles",
            },
        )

        diverged, fields = calendar_event_diverged(live, snap)

        assert diverged is False
        assert fields == []

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

    def test_divergence_includes_structured_values(self):
        snap = {
            "summary": "Meeting",
            "location": "",
            "description": "",
            "start": {
                "dateTime": "2026-01-01T10:00:00",
                "timeZone": "America/Los_Angeles",
            },
            "end": {
                "dateTime": "2026-01-01T11:00:00",
                "timeZone": "America/Los_Angeles",
            },
        }
        live = {
            **snap,
            "start": {
                "dateTime": "2026-01-01T12:00:00-08:00",
                "timeZone": "America/Los_Angeles",
            },
            "htmlLink": "https://calendar.google.com/event?eid=test",
        }
        mock_client = MagicMock()
        with patch(
            "selko.services.calendars.get_calendar_event",
            return_value=live,
        ), patch(
            "selko.services.calendars.get_latest_sync_snapshot",
            return_value=snap,
        ):
            with pytest.raises(CalendarDivergedError) as exc:
                assert_calendar_not_diverged(
                    mock_client, "user-1", "event-1", "gcal-1", force=False
                )

        assert exc.value.changed_fields == ["start"]
        assert exc.value.differences == [
            {
                "field": "start",
                "selko": snap["start"],
                "google": live["start"],
            }
        ]
        assert exc.value.google_event_url == live["htmlLink"]
