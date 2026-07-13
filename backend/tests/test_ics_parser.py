"""Unit tests for deterministic .ics attachment parser."""

from datetime import datetime, timezone

import pytest

from selko.services.ics_parser import parse_ics_attachments


# --- .ics content fixtures ---

BASIC_ICS = b"""\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
SUMMARY:Team Meeting
DTSTART:20260315T140000Z
DTEND:20260315T150000Z
LOCATION:Room A
DESCRIPTION:Weekly sync meeting
END:VEVENT
END:VCALENDAR"""

MULTIPLE_EVENTS_ICS = b"""\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
SUMMARY:Morning Standup
DTSTART:20260315T090000Z
DTEND:20260315T091500Z
LOCATION:Zoom
DESCRIPTION:Daily standup
END:VEVENT
BEGIN:VEVENT
SUMMARY:Lunch Meeting
DTSTART:20260315T120000Z
DTEND:20260315T130000Z
LOCATION:Cafeteria
DESCRIPTION:Team lunch
END:VEVENT
END:VCALENDAR"""

ALL_DAY_ICS = b"""\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
SUMMARY:Company Holiday
DTSTART;VALUE=DATE:20260401
DTEND;VALUE=DATE:20260402
DESCRIPTION:Spring holiday
END:VEVENT
END:VCALENDAR"""

NO_DTEND_ICS = b"""\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
SUMMARY:Quick Call
DTSTART:20260315T100000Z
DESCRIPTION:Brief discussion
END:VEVENT
END:VCALENDAR"""

EMPTY_VCALENDAR_ICS = b"""\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
END:VCALENDAR"""

TIMEZONE_ICS = b"""\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VTIMEZONE
TZID:America/New_York
BEGIN:STANDARD
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VEVENT
SUMMARY:NYC Meeting
DTSTART;TZID=America/New_York:20260315T100000
DTEND;TZID=America/New_York:20260315T110000
LOCATION:123 Broadway
DESCRIPTION:East coast meeting
END:VEVENT
END:VCALENDAR"""

MALFORMED_ICS = b"This is not valid iCalendar data"

EMAIL_METADATA = {
    "provider_message_id": "msg-ics-test",
    "subject": "Meeting Invite",
    "from_name": "Organizer",
    "from_email": "organizer@example.com",
    "date_sent": "2026-03-15T10:00:00Z",
}


class TestParseIcsAttachments:
    """Tests for parse_ics_attachments."""

    def test_parse_single_vevent(self):
        attachments = [
            {"data": BASIC_ICS, "mime_type": "text/calendar", "filename": "invite.ics"},
        ]

        result = parse_ics_attachments(attachments, EMAIL_METADATA)

        assert result is not None
        assert result.events_found is True
        assert len(result.events) == 1

        event = result.events[0]
        assert event.title == "Team Meeting"
        assert event.start_datetime == datetime(2026, 3, 15, 14, 0, tzinfo=timezone.utc)
        assert event.end_datetime == datetime(2026, 3, 15, 15, 0, tzinfo=timezone.utc)
        assert event.location == "Room A"
        assert event.description == "Weekly sync meeting"

    def test_parse_multiple_vevents(self):
        attachments = [
            {"data": MULTIPLE_EVENTS_ICS, "mime_type": "text/calendar", "filename": "events.ics"},
        ]

        result = parse_ics_attachments(attachments, EMAIL_METADATA)

        assert result is not None
        assert len(result.events) == 2
        assert result.events[0].title == "Morning Standup"
        assert result.events[1].title == "Lunch Meeting"

    def test_all_day_event(self):
        attachments = [
            {"data": ALL_DAY_ICS, "mime_type": "text/calendar", "filename": "holiday.ics"},
        ]

        result = parse_ics_attachments(attachments, EMAIL_METADATA)

        assert result is not None
        assert len(result.events) == 1

        event = result.events[0]
        assert event.title == "Company Holiday"
        # All-day events: DTSTART is a date, converted to midnight UTC
        assert event.start_datetime == datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
        # All-day DTEND is also a date
        assert event.end_datetime == datetime(2026, 4, 2, 0, 0, tzinfo=timezone.utc)
        # Regression: all_day flag must be set, not silently dropped
        assert event.all_day is True

    def test_timed_event_has_all_day_false(self):
        attachments = [
            {"data": NO_DTEND_ICS, "mime_type": "text/calendar", "filename": "quick.ics"},
        ]

        result = parse_ics_attachments(attachments, EMAIL_METADATA)

        assert result is not None
        assert result.events[0].all_day is False

    def test_missing_dtend_defaults_to_one_hour(self):
        attachments = [
            {"data": NO_DTEND_ICS, "mime_type": "text/calendar", "filename": "quick.ics"},
        ]

        result = parse_ics_attachments(attachments, EMAIL_METADATA)

        assert result is not None
        event = result.events[0]
        assert event.start_datetime == datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)
        assert event.end_datetime == datetime(2026, 3, 15, 11, 0, tzinfo=timezone.utc)

    def test_no_ics_attachments_returns_none(self):
        attachments = [
            {"data": b"image data", "mime_type": "image/jpeg", "filename": "photo.jpg"},
        ]

        result = parse_ics_attachments(attachments, EMAIL_METADATA)

        assert result is None

    def test_mixed_attachments_only_parses_ics(self):
        attachments = [
            {"data": b"image data", "mime_type": "image/jpeg", "filename": "photo.jpg"},
            {"data": BASIC_ICS, "mime_type": "text/calendar", "filename": "invite.ics"},
            {"data": b"pdf data", "mime_type": "application/pdf", "filename": "doc.pdf"},
        ]

        result = parse_ics_attachments(attachments, EMAIL_METADATA)

        assert result is not None
        assert len(result.events) == 1
        assert result.events[0].title == "Team Meeting"

    def test_malformed_ics_returns_none(self):
        attachments = [
            {"data": MALFORMED_ICS, "mime_type": "text/calendar", "filename": "bad.ics"},
        ]

        result = parse_ics_attachments(attachments, EMAIL_METADATA)

        assert result is None

    def test_empty_ics_no_vevents_returns_none(self):
        attachments = [
            {"data": EMPTY_VCALENDAR_ICS, "mime_type": "text/calendar", "filename": "empty.ics"},
        ]

        result = parse_ics_attachments(attachments, EMAIL_METADATA)

        assert result is None

    def test_timezone_aware_datetimes(self):
        attachments = [
            {"data": TIMEZONE_ICS, "mime_type": "text/calendar", "filename": "tz.ics"},
        ]

        result = parse_ics_attachments(attachments, EMAIL_METADATA)

        assert result is not None
        event = result.events[0]
        assert event.title == "NYC Meeting"
        # Should have timezone info
        assert event.start_datetime.tzinfo is not None
        assert event.location == "123 Broadway"

    def test_mime_type_detection(self):
        """text/calendar MIME type is detected regardless of filename."""
        attachments = [
            {"data": BASIC_ICS, "mime_type": "text/calendar", "filename": "meeting.dat"},
        ]

        result = parse_ics_attachments(attachments, EMAIL_METADATA)

        assert result is not None
        assert len(result.events) == 1

    def test_filename_fallback_detection(self):
        """.ics extension is detected when MIME type is generic."""
        attachments = [
            {"data": BASIC_ICS, "mime_type": "application/octet-stream", "filename": "invite.ics"},
        ]

        result = parse_ics_attachments(attachments, EMAIL_METADATA)

        assert result is not None
        assert len(result.events) == 1

    def test_email_metadata_propagated(self):
        """Email metadata is correctly set on the extraction result."""
        attachments = [
            {"data": BASIC_ICS, "mime_type": "text/calendar", "filename": "invite.ics"},
        ]

        result = parse_ics_attachments(attachments, EMAIL_METADATA)

        assert result is not None
        assert result.email_message_id == "msg-ics-test"
        assert result.sender_email == "organizer@example.com"
        assert result.sender_name == "Organizer"

    def test_empty_attachments_returns_none(self):
        result = parse_ics_attachments([], EMAIL_METADATA)
        assert result is None

    def test_ics_with_no_data_skipped(self):
        """Attachments with no data are skipped."""
        attachments = [
            {"data": None, "mime_type": "text/calendar", "filename": "empty.ics"},
        ]

        result = parse_ics_attachments(attachments, EMAIL_METADATA)

        assert result is None
