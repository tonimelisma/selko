from selko.services.ics_parser import parse_calendar_components
from selko.services.outlook import parse_outlook_message


# Validates: SEL-062
def test_ics_components_preserve_method_identity_and_sequence() -> None:
    payload = b"""BEGIN:VCALENDAR
METHOD:CANCEL
VERSION:2.0
BEGIN:VEVENT
UID: meeting-123
SEQUENCE:7
DTSTAMP:20260819T120000Z
STATUS:CANCELLED
RECURRENCE-ID;RANGE=THISANDFUTURE:20260820T130000Z
DTSTART:20260820T130000Z
DTEND:20260820T140000Z
SUMMARY:Cancelled
END:VEVENT
END:VCALENDAR
"""
    components = parse_calendar_components([payload])
    assert len(components) == 1
    assert components[0]["method"] == "CANCEL"
    assert components[0]["uid_hash"]
    assert components[0]["sequence"] == 7
    assert components[0]["recurrence_range"] == "THISANDFUTURE"
    assert components[0]["component_status"] == "CANCELLED"


# Validates: SEL-062
def test_malformed_ics_isolated_without_raising() -> None:
    assert parse_calendar_components([b"not-an-ics-file"]) == []


# Validates: SEL-063
def test_outlook_meeting_cancelled_without_associated_event_keeps_cancel_method() -> None:
    parsed = parse_outlook_message(
        {
            "id": "message-1",
            "meetingMessageType": "meetingCancelled",
            "subject": "Cancelled meeting",
            "receivedDateTime": "2026-08-19T12:00:00Z",
            "from": {"emailAddress": {"address": "sender@example.com"}},
        }
    )
    assert parsed["calendar_components"][0]["method"] == "CANCEL"
    assert parsed["calendar_components"][0]["uid_hash"] is None
