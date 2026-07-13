"""Deterministic .ics (iCalendar) attachment parser.

Parses RFC 5545 .ics attachments into CalendarEvent objects, skipping LLM
extraction entirely for emails with structured calendar data.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import icalendar

from selko.api.schemas.calendar import CalendarEvent, CalendarEventExtraction

logger = logging.getLogger(__name__)

INVITE_METHODS = {"REQUEST", "REPLY", "CANCEL", "COUNTER", "DECLINECOUNTER"}


def detect_invite_method(attachments: list[dict[str, Any]]) -> Optional[str]:
    """Return the uppercased METHOD of the first parseable .ics, or None.

    A real calendar-invite email (Google/Outlook meeting request, update,
    RSVP, or cancellation) carries one of INVITE_METHODS. Plain "add to
    calendar" .ics files use METHOD:PUBLISH or omit METHOD entirely and are
    not invites.
    """
    for att in _filter_ics_attachments(attachments):
        try:
            cal = icalendar.Calendar.from_ical(att["data"])
        except Exception:
            continue
        method = cal.get("METHOD")
        if method:
            return str(method).strip().upper()
    return None


def parse_ics_attachments(
    attachments: list[dict[str, Any]],
    email_metadata: dict[str, Any],
) -> Optional[CalendarEventExtraction]:
    """Parse .ics attachments into a CalendarEventExtraction.

    Filters attachments for .ics files (by MIME type or filename extension),
    parses them, and returns structured event data. Returns None if no .ics
    attachments are found or all parsing fails.

    Args:
        attachments: List of attachment dicts with keys: data (bytes),
            mime_type (str), filename (str).
        email_metadata: Dict with keys: provider_message_id, subject, from_name,
            from_email, date_sent.

    Returns:
        CalendarEventExtraction with parsed events, or None if no .ics
        attachments found or all parsing failed.
    """
    ics_attachments = _filter_ics_attachments(attachments)
    if not ics_attachments:
        return None

    all_events: list[CalendarEvent] = []

    for att in ics_attachments:
        try:
            events = _parse_single_ics(att["data"])
            all_events.extend(events)
        except Exception as e:
            filename = att.get("filename", "unknown")
            logger.warning(f"Failed to parse .ics attachment {filename}: {e}")

    if not all_events:
        return None

    return CalendarEventExtraction(
        email_message_id=email_metadata.get("provider_message_id", ""),
        email_date=email_metadata.get("date_sent") or None,
        sender_name=email_metadata.get("from_name"),
        sender_email=email_metadata.get("from_email", ""),
        events_found=True,
        events=all_events,
    )


def _filter_ics_attachments(
    attachments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter attachments to only .ics files.

    Matches on MIME type text/calendar or .ics filename extension.
    """
    result = []
    for att in attachments:
        mime_type = (att.get("mime_type") or "").lower()
        filename = (att.get("filename") or "").lower()

        if mime_type == "text/calendar" or filename.endswith(".ics"):
            if att.get("data"):
                result.append(att)
    return result


def _parse_single_ics(data: bytes) -> list[CalendarEvent]:
    """Parse a single .ics file into CalendarEvent objects.

    Args:
        data: Raw bytes of the .ics file.

    Returns:
        List of CalendarEvent objects extracted from VEVENT components.

    Raises:
        Exception: If the .ics data is malformed.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")

    cal = icalendar.Calendar.from_ical(data)
    events = []

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        event = _vevent_to_calendar_event(component)
        if event:
            events.append(event)

    return events


def _vevent_to_calendar_event(
    vevent: icalendar.Event,
) -> Optional[CalendarEvent]:
    """Convert a VEVENT component to a CalendarEvent.

    Args:
        vevent: An icalendar VEVENT component.

    Returns:
        CalendarEvent or None if the VEVENT lacks required fields.
    """
    summary = str(vevent.get("SUMMARY", "")).strip()
    if not summary:
        return None

    dtstart_prop = vevent.get("DTSTART")
    if not dtstart_prop:
        return None

    dtstart_val = dtstart_prop.dt
    is_all_day = isinstance(dtstart_val, date) and not isinstance(dtstart_val, datetime)

    start_dt = _to_datetime(dtstart_val)

    # End time
    dtend_prop = vevent.get("DTEND")
    if dtend_prop:
        end_dt = _to_datetime(dtend_prop.dt)
    elif is_all_day:
        end_dt = None
    else:
        # Default: 1 hour after start
        end_dt = start_dt + timedelta(hours=1)

    location = str(vevent.get("LOCATION", "")).strip() or None
    description = str(vevent.get("DESCRIPTION", "")).strip()

    # Extract RRULE for recurring events
    rrule = vevent.get("RRULE")
    recurrence_rule = None
    if rrule:
        recurrence_rule = f"RRULE:{rrule.to_ical().decode('utf-8')}"

    return CalendarEvent(
        title=summary,
        start_datetime=start_dt,
        end_datetime=end_dt,
        all_day=is_all_day,
        location=location,
        description=description,
        recurrence_rule=recurrence_rule,
    )


def _to_datetime(dt_value: Any) -> datetime:
    """Convert a date or datetime to a timezone-aware datetime.

    Args:
        dt_value: A date or datetime object from icalendar parsing.

    Returns:
        A datetime object (UTC if no timezone info present).
    """
    if isinstance(dt_value, datetime):
        if dt_value.tzinfo is None:
            return dt_value.replace(tzinfo=timezone.utc)
        return dt_value

    # date-only → midnight UTC
    if isinstance(dt_value, date):
        return datetime(dt_value.year, dt_value.month, dt_value.day, tzinfo=timezone.utc)

    return datetime.now(timezone.utc)
