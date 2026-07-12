"""Civil (wall-clock) time helpers.

Emails and LLMs speak local wall-clock times. Selko owns timezone conversion.
Never trust LLM-emitted offsets — strip them and interpret clock face in the
user's IANA timezone. Trusted sources (ICS, Google Calendar) keep absolute
instants.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

DEFAULT_USER_TIMEZONE = "America/New_York"


def resolve_zone(user_timezone: Optional[str]) -> ZoneInfo:
    """Return a ZoneInfo, falling back to America/New_York on invalid input."""
    name = user_timezone or DEFAULT_USER_TIMEZONE
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError):
        return ZoneInfo(DEFAULT_USER_TIMEZONE)


def resolve_timezone_name(user_timezone: Optional[str]) -> str:
    """Return a valid IANA timezone name string."""
    name = user_timezone or DEFAULT_USER_TIMEZONE
    try:
        ZoneInfo(name)
        return name
    except (KeyError, ValueError):
        return DEFAULT_USER_TIMEZONE


def parse_datetime(value: Any) -> Optional[datetime]:
    """Parse a datetime or ISO string into a datetime (may be naive or aware)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        try:
            d = date.fromisoformat(text)
            return datetime(d.year, d.month, d.day)
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def as_civil_naive(value: Any) -> Optional[datetime]:
    """Return a naive datetime using the clock face only (drop any offset).

    LLM outputs like ``2026-09-13T07:00:00+00:00`` mean "7:00 on the wall",
    not 7:00 UTC.
    """
    dt = parse_datetime(value)
    if dt is None:
        return None
    return dt.replace(tzinfo=None)


def localize_civil(
    value: Any,
    user_timezone: Optional[str] = None,
) -> Optional[datetime]:
    """Interpret value as civil wall time in user_timezone → aware datetime."""
    naive = as_civil_naive(value)
    if naive is None:
        return None
    return naive.replace(tzinfo=resolve_zone(user_timezone))


def ensure_aware(
    value: Any,
    user_timezone: Optional[str] = None,
) -> Optional[datetime]:
    """Ensure an absolute datetime is timezone-aware.

    Naive values are treated as civil in user_timezone. Already-aware values
    keep their absolute instant (ICS / Google Calendar).
    """
    dt = parse_datetime(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=resolve_zone(user_timezone))
    return dt


def to_civil_iso(value: Any, user_timezone: Optional[str] = None) -> Optional[str]:
    """Format a stored/absolute datetime as naive local ISO in user_timezone."""
    dt = parse_datetime(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        civil = dt
    else:
        civil = dt.astimezone(resolve_zone(user_timezone)).replace(tzinfo=None)
    return civil.strftime("%Y-%m-%dT%H:%M:%S")


def to_storage_iso(
    value: Any,
    user_timezone: Optional[str] = None,
    *,
    treat_as_civil: bool = True,
) -> Optional[str]:
    """Convert a datetime to an ISO string suitable for DB timestamptz storage."""
    if treat_as_civil:
        aware = localize_civil(value, user_timezone)
    else:
        aware = ensure_aware(value, user_timezone)
    if aware is None:
        return None
    return aware.isoformat()


def datetimes_equal(
    before: Any,
    after: Any,
    user_timezone: Optional[str] = None,
) -> bool:
    """True when before/after are the same civil appointment in user_timezone.

    1. Absolute instant equality (trusted offsets match).
    2. Else interpret ``after`` as civil wall time (LLM may stamp +00:00 on
       local numbers) and compare to ``before``'s absolute instant.
    """
    if before is None and after is None:
        return True
    if before is None or after is None:
        if before == "" and after == "":
            return True
        if (before is None or before == "") and (after is None or after == ""):
            return True
        return False

    b = ensure_aware(before, user_timezone)
    a = ensure_aware(after, user_timezone)
    if b is not None and a is not None:
        if b.astimezone(timezone.utc).replace(microsecond=0) == a.astimezone(
            timezone.utc
        ).replace(microsecond=0):
            return True

    # LLM after-value: clock face in user TZ vs baseline absolute
    a_civil = localize_civil(after, user_timezone)
    if b is not None and a_civil is not None:
        if b.astimezone(timezone.utc).replace(microsecond=0) == a_civil.astimezone(
            timezone.utc
        ).replace(microsecond=0):
            return True

    return False


def gcal_timed_fields(
    value: Any,
    user_timezone: Optional[str] = None,
) -> Optional[dict[str, str]]:
    """Build Google Calendar start/end: naive dateTime + IANA timeZone.

    Never combine a numeric offset with timeZone — offset wins at Google and
    produces wrong wall times on the calendar.
    """
    civil = to_civil_iso(value, user_timezone)
    if civil is None:
        return None
    return {
        "dateTime": civil,
        "timeZone": resolve_timezone_name(user_timezone),
    }
