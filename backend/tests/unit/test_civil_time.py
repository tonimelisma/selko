"""Tests for civil wall-clock time helpers."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from selko.services.civil_time import (
    as_civil_naive,
    datetimes_equal,
    gcal_timed_fields,
    localize_civil,
    to_civil_iso,
    to_storage_iso,
)


class TestLocalizeCivil:
    def test_strips_utc_offset_and_attaches_user_tz(self):
        """Regression: LLM 07:00+00:00 means 7am local, not midnight Pacific."""
        aware = localize_civil("2026-09-13T07:00:00+00:00", "America/Los_Angeles")
        assert aware is not None
        assert aware.hour == 7
        assert aware.tzinfo == ZoneInfo("America/Los_Angeles")
        # Absolute instant is 14:00 UTC (PDT), not 07:00 UTC
        assert aware.astimezone(timezone.utc).hour == 14

    def test_naive_localizes_to_user_tz(self):
        aware = localize_civil("2026-09-13T10:00:00", "America/Los_Angeles")
        assert aware is not None
        assert aware.isoformat().startswith("2026-09-13T10:00:00")
        assert "-07:00" in aware.isoformat()

    def test_as_civil_naive_drops_offset(self):
        assert as_civil_naive("2026-09-13T07:00:00+00:00") == datetime(2026, 9, 13, 7, 0, 0)


class TestStorageAndGcal:
    def test_storage_iso_civil_from_mislabeled_utc(self):
        iso = to_storage_iso(
            "2026-09-13T10:00:00+00:00",
            "America/Los_Angeles",
            treat_as_civil=True,
        )
        assert iso is not None
        assert iso.startswith("2026-09-13T10:00:00")
        assert "-07:00" in iso

    def test_storage_iso_absolute_keeps_instant(self):
        iso = to_storage_iso(
            "2026-09-13T17:00:00+00:00",
            "America/Los_Angeles",
            treat_as_civil=False,
        )
        assert iso is not None
        dt = datetime.fromisoformat(iso)
        assert dt.astimezone(timezone.utc).hour == 17

    def test_gcal_fields_are_naive_plus_timezone(self):
        fields = gcal_timed_fields("2026-09-13T17:00:00+00:00", "America/Los_Angeles")
        assert fields == {
            "dateTime": "2026-09-13T10:00:00",
            "timeZone": "America/Los_Angeles",
        }
        assert "+" not in fields["dateTime"]
        assert "Z" not in fields["dateTime"]


class TestDatetimesEqual:
    def test_equivalent_offsets_equal(self):
        assert datetimes_equal(
            "2026-09-13T10:00:00-07:00",
            "2026-09-13T17:00:00+00:00",
            "America/Los_Angeles",
        )

    def test_llm_utc_stamp_of_same_wall_time_equals_baseline(self):
        """10:00+00:00 from LLM vs true 10:00 PDT baseline → equal when civil."""
        assert datetimes_equal(
            "2026-09-13T10:00:00-07:00",
            "2026-09-13T10:00:00+00:00",
            "America/Los_Angeles",
        )

    def test_real_time_change_not_equal(self):
        assert not datetimes_equal(
            "2026-09-13T10:00:00-07:00",
            "2026-09-13T11:00:00-07:00",
            "America/Los_Angeles",
        )

    def test_to_civil_iso(self):
        assert to_civil_iso("2026-09-13T17:00:00+00:00", "America/Los_Angeles") == (
            "2026-09-13T10:00:00"
        )
