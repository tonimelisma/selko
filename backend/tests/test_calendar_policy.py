"""Unit tests for all-day materialization policy."""

from datetime import datetime, time
from zoneinfo import ZoneInfo


from selko.services.calendar_policy import (
    AllDayDisplayMode,
    AllDayPolicy,
    materialize_all_day_event,
    parse_time_value,
)


TZ = "America/New_York"
ZONE = ZoneInfo(TZ)


def _source(
    *,
    title: str = "Water Day",
    start: str = "2026-07-27T00:00:00",
    end: str | None = None,
    all_day: bool = True,
    **extra,
) -> dict:
    data = {
        "title": title,
        "start_datetime": start,
        "end_datetime": end,
        "all_day": all_day,
        "location": None,
        "description": "Wear water colors",
        "importance": "fyi",
        "source_quote": "Water Day on Monday",
    }
    data.update(extra)
    return data


class TestMaterializeAllDayEvent:
    def test_all_day_mode_unchanged(self):
        source = _source()
        out = materialize_all_day_event(
            source, AllDayPolicy(AllDayDisplayMode.ALL_DAY), TZ
        )
        assert out is not source
        assert out == source
        assert out["all_day"] is True

    def test_day_9_to_5_one_day(self):
        source = _source(end="2026-07-27T23:59:59")
        out = materialize_all_day_event(
            source, AllDayPolicy(AllDayDisplayMode.DAY_9_TO_5), TZ
        )
        assert out["all_day"] is False
        assert out["start_datetime"] == "2026-07-27T09:00:00-04:00"
        assert out["end_datetime"] == "2026-07-27T17:00:00-04:00"
        # Source untouched
        assert source["all_day"] is True
        assert source["start_datetime"] == "2026-07-27T00:00:00"

    def test_morning_8_to_9(self):
        source = _source()
        out = materialize_all_day_event(
            source, AllDayPolicy(AllDayDisplayMode.MORNING_8_TO_9), TZ
        )
        assert out["all_day"] is False
        assert out["start_datetime"] == "2026-07-27T08:00:00-04:00"
        assert out["end_datetime"] == "2026-07-27T09:00:00-04:00"

    def test_custom_window(self):
        policy = AllDayPolicy(
            AllDayDisplayMode.CUSTOM, custom_start=time(10, 30), custom_end=time(14, 0)
        )
        out = materialize_all_day_event(_source(), policy, TZ)
        assert out["all_day"] is False
        assert out["start_datetime"] == "2026-07-27T10:30:00-04:00"
        assert out["end_datetime"] == "2026-07-27T14:00:00-04:00"

    def test_missing_end_is_one_covered_day(self):
        out = materialize_all_day_event(
            _source(end=None), AllDayPolicy(AllDayDisplayMode.DAY_9_TO_5), TZ
        )
        assert out["start_datetime"] == "2026-07-27T09:00:00-04:00"
        assert out["end_datetime"] == "2026-07-27T17:00:00-04:00"

    def test_multi_day_exclusive_end_midnight_stays_all_day(self):
        # Exclusive end Feb 16 → last covered Feb 15: three days, not one block
        # from Friday 9:00 to Sunday 17:00.
        source = _source(
            title="President's Day Weekend",
            start="2026-02-13T00:00:00",
            end="2026-02-16T00:00:00",
        )
        out = materialize_all_day_event(
            source, AllDayPolicy(AllDayDisplayMode.DAY_9_TO_5), TZ
        )
        assert out == source

    def test_multi_day_inclusive_end_of_day_stays_all_day(self):
        source = _source(
            start="2026-07-20T00:00:00",
            end="2026-07-22T23:59:59",
        )
        out = materialize_all_day_event(
            source, AllDayPolicy(AllDayDisplayMode.MORNING_8_TO_9), TZ
        )
        assert out == source

    def test_season_span_is_never_one_two_month_timed_block(self):
        """Regression: "opens Nov 20, runs through Jan 18" under morning 8-9.

        Production stored 2026-11-20 08:00 -> 2027-01-18 09:00 Pacific, a
        single continuous event covering the whole season.
        """
        source = _source(
            title="Skating rink opens",
            start="2026-11-20T00:00:00",
            end="2027-01-18T23:59:59",
        )
        out = materialize_all_day_event(
            source, AllDayPolicy(AllDayDisplayMode.MORNING_8_TO_9), "America/Los_Angeles"
        )
        assert out["all_day"] is True
        assert out["start_datetime"] == source["start_datetime"]
        assert out["end_datetime"] == source["end_datetime"]

    def test_exclusive_next_midnight_is_still_one_day(self):
        # A single day written GCal-style (end = next midnight) is one covered
        # day, so the window still applies.
        source = _source(start="2026-07-27T00:00:00", end="2026-07-28T00:00:00")
        out = materialize_all_day_event(
            source, AllDayPolicy(AllDayDisplayMode.MORNING_8_TO_9), TZ
        )
        assert out["all_day"] is False
        assert out["start_datetime"] == "2026-07-27T08:00:00-04:00"
        assert out["end_datetime"] == "2026-07-27T09:00:00-04:00"

    def test_dst_spring_forward_preserves_wall_clock(self):
        # 2026-03-08 is US spring-forward Sunday in America/New_York
        source = _source(start="2026-03-08T00:00:00", end=None)
        out = materialize_all_day_event(
            source, AllDayPolicy(AllDayDisplayMode.DAY_9_TO_5), TZ
        )
        start = datetime.fromisoformat(out["start_datetime"])
        end = datetime.fromisoformat(out["end_datetime"])
        assert start.astimezone(ZONE).hour == 9
        assert end.astimezone(ZONE).hour == 17
        assert start.tzinfo is not None

    def test_timed_event_unchanged_under_every_policy(self):
        source = _source(
            title="Standup",
            start="2026-07-27T10:00:00-04:00",
            end="2026-07-27T10:30:00-04:00",
            all_day=False,
        )
        original = dict(source)
        for mode in AllDayDisplayMode:
            policy = AllDayPolicy(
                mode,
                custom_start=time(9, 0) if mode == AllDayDisplayMode.CUSTOM else None,
                custom_end=time(17, 0) if mode == AllDayDisplayMode.CUSTOM else None,
            )
            out = materialize_all_day_event(source, policy, TZ)
            assert out == original
            assert source == original


class TestValidateAllDayPolicy:


    def test_parse_time_value(self):
        assert parse_time_value("09:30:00") == time(9, 30)
        assert parse_time_value("9:30") == time(9, 30)
