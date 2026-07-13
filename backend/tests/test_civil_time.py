"""Unit tests for civil_time helpers, focused on gcal_all_day_fields (WS5)."""

from selko.services.civil_time import gcal_all_day_fields


class TestGcalAllDayFields:
    """Tests for the shared all-day Google Calendar payload helper."""

    def test_multi_day_closure_los_angeles(self):
        """3-day closure stored as local-midnight..local-23:59:59 (America/Los_Angeles)."""
        start, end = gcal_all_day_fields(
            "2026-08-12T07:00:00Z", "2026-08-15T06:59:59Z", "America/Los_Angeles"
        )
        assert start == {"date": "2026-08-12"}
        assert end == {"date": "2026-08-15"}  # exclusive end -> renders Aug 12-14

    def test_single_day_with_no_end(self):
        start, end = gcal_all_day_fields("2026-08-12T07:00:00Z", None, "America/Los_Angeles")
        assert start == {"date": "2026-08-12"}
        assert end == {"date": "2026-08-13"}

    def test_single_day_with_matching_end(self):
        """A same-day end (local 23:59:59) must still produce an exclusive next-day end."""
        start, end = gcal_all_day_fields(
            "2026-08-12T07:00:00Z", "2026-08-13T06:59:59Z", "America/Los_Angeles"
        )
        assert start == {"date": "2026-08-12"}
        assert end == {"date": "2026-08-13"}

    def test_end_already_at_exclusive_midnight(self):
        """An end stored at exact local midnight already points at the exclusive day."""
        start, end = gcal_all_day_fields(
            "2026-08-12T07:00:00Z", "2026-08-14T07:00:00Z", "America/Los_Angeles"
        )
        assert start == {"date": "2026-08-12"}
        assert end == {"date": "2026-08-14"}

    def test_helsinki_midnight_crosses_utc_day_boundary(self):
        """Local midnight in a timezone east of UTC stores as the previous UTC day."""
        start, end = gcal_all_day_fields(
            "2026-08-11T21:00:00Z", None, "Europe/Helsinki"
        )
        assert start == {"date": "2026-08-12"}
        assert end == {"date": "2026-08-13"}
