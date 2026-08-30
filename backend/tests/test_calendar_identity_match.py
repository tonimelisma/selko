"""Identity matching against events that live in the user's Google Calendar.

Production carried 364 events and 14 identity hints, every one of kind
`join_url` and none of kind `ical_uid`. An invite the user had already accepted
lived in Google Calendar and not in `events`, so no stored hint could reach it:
it was compared by title, time and an LLM judgement, and when that declined the
same event was proposed as New again. `iCalUID` is returned on every Google
Calendar event and is the same UID the invite carried.
"""

from __future__ import annotations

from selko.services.event_identity import (
    canonical_ical_uid,
    canonical_join_url,
    hints_from_calendar_event,
    match_by_identity,
)


def test_calendar_event_yields_its_ical_uid_as_authoritative():
    hints = hints_from_calendar_event(
        {"iCalUID": "loop-1@example.com", "hangoutLink": "https://meet.example.com/abc"}
    )
    kinds = {hint.kind: hint.strength for hint in hints}
    assert kinds["ical_uid"] == "authoritative"
    assert kinds["join_url"] == "supporting"


def test_matching_uid_proves_the_user_already_has_the_event():
    calendar = hints_from_calendar_event({"iCalUID": "invite-9@example.com"})
    incoming = [canonical_ical_uid("invite-9@example.com")]
    assert match_by_identity(incoming, calendar) is not None


def test_a_different_uid_is_not_a_match():
    calendar = hints_from_calendar_event({"iCalUID": "invite-9@example.com"})
    incoming = [canonical_ical_uid("invite-10@example.com")]
    assert match_by_identity(incoming, calendar) is None


def test_a_shared_join_url_alone_never_merges_two_events():
    """The interview-loop regression, stated as a test.

    One production email produced five interview slots at 17:00, 18:00, 21:30
    and 23:00 on one day. Sessions in a loop routinely share a meeting link, so
    treating a join URL as proof of identity would collapse five real events
    into one -- worse than the duplicate this feature exists to prevent. Only an
    authoritative hint decides.
    """
    calendar = hints_from_calendar_event(
        {"iCalUID": "slot-1@example.com", "hangoutLink": "https://meet.example.com/loop"}
    )
    incoming = [canonical_join_url("https://meet.example.com/loop")]
    assert match_by_identity(incoming, calendar) is None


def test_recurring_occurrence_is_distinguished_by_its_original_start():
    """Same series UID, different occurrence: must not match the wrong instance."""
    september = hints_from_calendar_event({
        "iCalUID": "weekly@example.com",
        "originalStartTime": {"dateTime": "2026-09-09T17:00:00Z"},
    })
    october_incoming = [
        canonical_ical_uid("weekly@example.com", "2026-10-07T17:00:00Z")
    ]
    assert match_by_identity(october_incoming, september) is None

    september_incoming = [
        canonical_ical_uid("weekly@example.com", "2026-09-09T17:00:00Z")
    ]
    assert match_by_identity(september_incoming, september) is not None


def test_conference_entry_point_supplies_the_join_url():
    hints = hints_from_calendar_event({
        "iCalUID": "conf@example.com",
        "conferenceData": {
            "entryPoints": [
                {"entryPointType": "phone", "uri": "tel:+15551234567"},
                {"entryPointType": "video", "uri": "https://meet.example.com/xyz"},
            ]
        },
    })
    join = [hint for hint in hints if hint.kind == "join_url"]
    assert len(join) == 1
    assert join[0].value_hash == canonical_join_url("https://meet.example.com/xyz").value_hash


def test_a_calendar_event_without_identity_yields_nothing():
    assert hints_from_calendar_event({"summary": "Untitled"}) == []
    assert match_by_identity([canonical_ical_uid("x@example.com")], []) is None
