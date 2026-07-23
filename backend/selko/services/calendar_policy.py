"""All-day event materialization policy.

The LLM owns source truth (``all_day: true`` when the email gives a date but
no meaningful time). A single global user preference decides whether Selko
keeps the all-day event or turns it into a timed block before dedup/persist.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Any, Optional

from selko.services.civil_time import as_civil_naive, to_storage_iso


class AllDayDisplayMode(StrEnum):
    ALL_DAY = "all_day"
    DAY_9_TO_5 = "day_9_to_5"
    MORNING_8_TO_9 = "morning_8_to_9"
    CUSTOM = "custom"


@dataclass(frozen=True)
class AllDayPolicy:
    mode: AllDayDisplayMode
    custom_start: time | None = None
    custom_end: time | None = None


_PRESET_WINDOWS: dict[AllDayDisplayMode, tuple[time, time]] = {
    AllDayDisplayMode.DAY_9_TO_5: (time(9, 0), time(17, 0)),
    AllDayDisplayMode.MORNING_8_TO_9: (time(8, 0), time(9, 0)),
}


class CalendarPolicyError(ValueError):
    """Raised when an all-day policy cannot be applied (invalid custom times)."""


def parse_time_value(value: Any) -> time | None:
    """Parse a DB/API time value into ``datetime.time``."""
    if value is None or value == "":
        return None
    if isinstance(value, time):
        return value.replace(microsecond=0)
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    text = str(value).strip()
    if not text:
        return None
    if "." in text:
        text = text.split(".", 1)[0]
    parts = text.split(":")
    try:
        if len(parts) == 2:
            return time(int(parts[0]), int(parts[1]))
        if len(parts) == 3:
            return time(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError as e:
        raise CalendarPolicyError(f"Invalid time value: {value!r}") from e
    raise CalendarPolicyError(f"Invalid time value: {value!r}")


def all_day_policy_from_settings(settings: dict[str, Any] | None) -> AllDayPolicy:
    """Build an AllDayPolicy from a user_calendar_settings row (or defaults)."""
    settings = settings or {}
    raw_mode = settings.get("all_day_display_mode") or AllDayDisplayMode.ALL_DAY
    try:
        mode = AllDayDisplayMode(raw_mode)
    except ValueError as e:
        raise CalendarPolicyError(
            f"Invalid all_day_display_mode: {raw_mode!r}"
        ) from e
    return AllDayPolicy(
        mode=mode,
        custom_start=parse_time_value(settings.get("all_day_custom_start")),
        custom_end=parse_time_value(settings.get("all_day_custom_end")),
    )


def validate_all_day_policy(
    mode: AllDayDisplayMode | str,
    custom_start: Any = None,
    custom_end: Any = None,
) -> AllDayPolicy:
    """Validate settings input; raise CalendarPolicyError on invalid custom."""
    try:
        resolved_mode = AllDayDisplayMode(mode)
    except ValueError as e:
        raise CalendarPolicyError(f"Invalid all_day_display_mode: {mode!r}") from e

    start = parse_time_value(custom_start)
    end = parse_time_value(custom_end)

    if resolved_mode == AllDayDisplayMode.CUSTOM:
        if start is None or end is None:
            raise CalendarPolicyError(
                "Custom all-day display mode requires both start and end times"
            )
        if end <= start:
            raise CalendarPolicyError(
                "Custom all-day end time must be later than start time"
            )

    return AllDayPolicy(mode=resolved_mode, custom_start=start, custom_end=end)


def _window_for_policy(policy: AllDayPolicy) -> tuple[time, time]:
    if policy.mode == AllDayDisplayMode.ALL_DAY:
        raise CalendarPolicyError("ALL_DAY mode has no timed window")
    if policy.mode == AllDayDisplayMode.CUSTOM:
        if policy.custom_start is None or policy.custom_end is None:
            raise CalendarPolicyError(
                "Custom all-day display mode requires both start and end times"
            )
        if policy.custom_end <= policy.custom_start:
            raise CalendarPolicyError(
                "Custom all-day end time must be later than start time"
            )
        return policy.custom_start, policy.custom_end
    return _PRESET_WINDOWS[policy.mode]


def _civil_date(value: Any) -> Optional[date]:
    civil = as_civil_naive(value)
    if civil is None:
        return None
    return civil.date()


def _last_covered_date(start_date: date, end_value: Any) -> date:
    """Resolve the last civil day covered by an all-day source event.

    Selko stores all-day ends in two shapes:
    - Exclusive midnight (GCal-style): ``2026-02-16T00:00:00`` means last
      covered day is Feb 15.
    - Inclusive end-of-day: ``2026-07-20T23:59:59`` means last covered is
      Jul 20.
    Missing end → single covered day.
    """
    if end_value is None or end_value == "":
        return start_date

    end_civil = as_civil_naive(end_value)
    if end_civil is None:
        return start_date

    end_date = end_civil.date()
    if end_civil.time() == time(0, 0, 0):
        last = end_date - timedelta(days=1)
    else:
        last = end_date
    return max(last, start_date)


def materialize_all_day_event(
    source_event: dict[str, Any],
    policy: AllDayPolicy,
    timezone_name: str,
) -> dict[str, Any]:
    """Return an independent copy of ``source_event`` with policy applied.

    Timed source events and ``all_day`` policy mode are returned unchanged
    (aside from a deep copy). Timed preset/custom modes set ``all_day=false``
    and rewrite start/end to the chosen civil window in ``timezone_name``.
    """
    event = deepcopy(source_event)

    if not event.get("all_day"):
        return event
    if policy.mode == AllDayDisplayMode.ALL_DAY:
        return event

    start_date = _civil_date(event.get("start_datetime"))
    if start_date is None:
        return event

    last_date = _last_covered_date(start_date, event.get("end_datetime"))
    start_clock, end_clock = _window_for_policy(policy)

    start_naive = datetime.combine(start_date, start_clock)
    end_naive = datetime.combine(last_date, end_clock)

    event["all_day"] = False
    event["start_datetime"] = to_storage_iso(
        start_naive, timezone_name, treat_as_civil=True
    )
    event["end_datetime"] = to_storage_iso(
        end_naive, timezone_name, treat_as_civil=True
    )
    return event
