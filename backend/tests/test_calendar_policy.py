"""Unit tests for all-day materialization policy."""

from datetime import datetime, time
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from selko.services.calendar_policy import (
    AllDayDisplayMode,
    AllDayPolicy,
    CalendarPolicyError,
    materialize_all_day_event,
    parse_time_value,
    validate_all_day_policy,
)
from selko.services.events import create_event


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

    def test_multi_day_exclusive_end_midnight(self):
        # Exclusive end Feb 16 → last covered Feb 15
        source = _source(
            title="President's Day Weekend",
            start="2026-02-13T00:00:00",
            end="2026-02-16T00:00:00",
        )
        out = materialize_all_day_event(
            source, AllDayPolicy(AllDayDisplayMode.DAY_9_TO_5), TZ
        )
        assert out["start_datetime"] == "2026-02-13T09:00:00-05:00"
        assert out["end_datetime"] == "2026-02-15T17:00:00-05:00"

    def test_multi_day_inclusive_end_of_day(self):
        source = _source(
            start="2026-07-20T00:00:00",
            end="2026-07-22T23:59:59",
        )
        out = materialize_all_day_event(
            source, AllDayPolicy(AllDayDisplayMode.MORNING_8_TO_9), TZ
        )
        assert out["start_datetime"] == "2026-07-20T08:00:00-04:00"
        assert out["end_datetime"] == "2026-07-22T09:00:00-04:00"

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
    def test_custom_requires_both_times(self):
        with pytest.raises(CalendarPolicyError):
            validate_all_day_policy("custom", custom_start="09:00", custom_end=None)

    def test_custom_end_must_be_later(self):
        with pytest.raises(CalendarPolicyError):
            validate_all_day_policy("custom", custom_start="17:00", custom_end="09:00")

    def test_parse_time_value(self):
        assert parse_time_value("09:30:00") == time(9, 30)
        assert parse_time_value("9:30") == time(9, 30)


class TestCreateEventSourceMaterializedSplit:
    def test_create_event_stores_source_in_extracted_data(self):
        events_table = MagicMock()
        sources_table = MagicMock()
        events_table.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "evt-1"}]
        )
        sources_table.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )
        sources_table.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "src-1"}]
        )

        mock_client = MagicMock()

        def table(name):
            if name == "events":
                return events_table
            if name == "event_sources":
                return sources_table
            return MagicMock()

        mock_client.table.side_effect = table

        source = _source(end="2026-07-27T23:59:59")
        materialized = materialize_all_day_event(
            source, AllDayPolicy(AllDayDisplayMode.DAY_9_TO_5), TZ
        )

        with patch(
            "selko.services.events.generate_source_attribution", return_value=None
        ):
            event_id = create_event(
                mock_client,
                "user-1",
                materialized,
                "email-1",
                source_event_data=source,
            )

        assert event_id == "evt-1"
        events_row = events_table.insert.call_args[0][0]
        extracted = sources_table.insert.call_args[0][0]["extracted_data"]
        assert events_row["all_day"] is False
        assert events_row["start_datetime"] == "2026-07-27T09:00:00-04:00"
        assert events_row["end_datetime"] == "2026-07-27T17:00:00-04:00"
        assert extracted["all_day"] is True
        assert extracted["start_datetime"] == "2026-07-27T00:00:00"


class TestEnsureEmailEventSourceIdempotent:
    def test_second_link_reuses_existing_row(self):
        from selko.services.events import ensure_email_event_source

        sources_table = MagicMock()
        # First call: no existing row → insert
        empty = MagicMock(data=[])
        existing = MagicMock(data=[{"id": "src-existing"}])
        select_chain = MagicMock()
        select_chain.eq.return_value = select_chain
        select_chain.limit.return_value.execute.side_effect = [empty, existing]
        sources_table.select.return_value = select_chain
        sources_table.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "src-new"}]
        )

        mock_client = MagicMock()
        mock_client.table.return_value = sources_table

        first = ensure_email_event_source(
            mock_client,
            event_id="evt-1",
            email_id="email-1",
            extracted_data={"title": "Water Day"},
        )
        second = ensure_email_event_source(
            mock_client,
            event_id="evt-1",
            email_id="email-1",
            extracted_data={"title": "Water Day"},
        )

        assert first == "src-new"
        assert second == "src-existing"
        assert sources_table.insert.call_count == 1

