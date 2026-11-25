"""A declined event stays declined, and never becomes a duplicate.

review-queue-integrity.md 8.2 requires that a later email about an event the
user rejected (or that was cancelled) record its matched source and outcome and
otherwise leave the event alone. Ingestion did the opposite: the match fell
through to the propose-and-promote branch, which revived the event.

The tempting fix -- drop declined events from the candidate set -- is worse than
the bug. The declined row is the *correct* identity match; hiding it makes the
next email create a fresh New-lane card for something the user already said no
to. So these tests assert both halves: the match still happens, and it decides
nothing.

Runs on a real database through the real match and commit; the LLM and the
calendar provider's live read are mocked.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from selko.api.schemas.calendar import CalendarEvent, CalendarEventExtraction
from selko.services.events import find_matching_event, save_extracted_events
from tests.event_pipeline import (
    claimed_email,
    event_at,
    future_local,
    gateway,
    ical_uid,
    lease,
    providers_offline,
    spy_commit,  # noqa: F401  (fixture)
)

START = future_local()


def _extraction(booking_confirmed: bool = False):
    return CalendarEventExtraction(
        email_message_id="msg-declined",
        sender_email="sender@example.com",
        events_found=True,
        booking_confirmed=booking_confirmed,
        events=[CalendarEvent(
            title="Team Meeting",
            start_datetime=START,
            end_datetime=START + timedelta(hours=1),
            location="Room A",
            description="Weekly sync",
        )],
    )


def _sources(db, event_id):
    return db.query("SELECT email_id, source_type FROM event_sources WHERE event_id = ?", (event_id,))


def _save(db, factory, declined, extraction, *, cancellation_mode=False, propose=None):
    user = factory.user()
    event = event_at(factory, user, START, review_status=declined)
    email = claimed_email(factory, user)
    if cancellation_mode:
        # An organizer cancellation matches by its iCalendar UID, never by text.
        ical_uid(factory, user, email, "uid-declined", event_id=event, method="CANCEL")
    with providers_offline(), \
         patch("selko.services.events.event_processing.compare_events", return_value=event), \
         patch("selko.services.events.event_processing.propose_event_update",
               side_effect=propose or AssertionError("no LLM call for a declined match")) as llm:
        counts = save_extracted_events(
            db, gateway(), user, email, extraction, cancellation_mode=cancellation_mode,
            **lease(db, email),
        )
    return counts, event, email, llm


@pytest.mark.parametrize("declined", ["rejected", "cancelled"])
def test_an_update_matching_a_declined_event_records_only(db, factory, spy_commit, declined):
    counts, event, email, propose = _save(db, factory, declined, _extraction())

    assert counts == (0, 0), "a declined match changes nothing"
    decision = spy_commit.decisions[0]
    assert decision["intent"] == "record_only"
    assert decision["fields"] == {}
    assert "change_set" not in decision["source"]
    # No LLM call for a change the user will never see.
    propose.assert_not_called()
    # The provenance is recorded and the decision stands.
    assert factory.row("events", event)["review_status"] == declined
    assert [s["email_id"] for s in _sources(db, event)] == [email]
    assert db.query("SELECT 1 FROM event_change_proposals WHERE event_id = ?", (event,)) == []
    assert db.query("SELECT 1 FROM calendar_work_items WHERE event_id = ?", (event,)) == []
    assert db.query_one("SELECT count(*) FROM events")[0] == 1, "no duplicate in New"


@pytest.mark.parametrize("declined", ["rejected", "cancelled"])
def test_a_cancellation_matching_a_declined_event_records_only(db, factory, spy_commit, declined):
    """Cancelling a declined event would revive it and queue a provider write."""
    _, event, _, _ = _save(db, factory, declined, _extraction(), cancellation_mode=True)

    decision = spy_commit.decisions[0]
    assert decision["intent"] == "record_only"
    assert decision["fields"] == {}
    assert factory.row("events", event)["review_status"] == declined
    assert db.query("SELECT 1 FROM calendar_work_items WHERE event_id = ?", (event,)) == []


@pytest.mark.parametrize("declined", ["rejected", "cancelled"])
def test_a_declined_adopted_event_is_matched_not_adopted_again(db, factory, declined):
    """The provider-event lookup must see declined rows.

    An event adopted from the user's own Google Calendar is not written back
    until they accept, so it carries no selko_event_id and the calendar
    read-back keeps matching it. If the lookup that maps that provider event to
    its existing Selko row skips declined rows, every later email adopts it
    again -- a duplicate of something the user rejected.
    """
    user = factory.user()
    # The adopted row starts on another day, so only the provider-id lookup finds it.
    event = factory.event(
        user, review_status=declined, title="Team Meeting",
        start_datetime="2026-05-01T14:00:00.000000Z", google_calendar_event_id="abc-123",
    )
    live = [{"id": "abc-123", "summary": "Team Meeting",
             "start": {"dateTime": "2026-05-09T14:00:00Z"},
             "end": {"dateTime": "2026-05-09T15:00:00Z"}}]

    with providers_offline(live), \
         patch("selko.services.events.event_processing.compare_events", return_value="gcal:abc-123"):
        match = find_matching_event(
            db, MagicMock(), user,
            {"title": "Team Meeting", "start_datetime": "2026-05-09T14:00:00Z",
             "end_datetime": "2026-05-09T15:00:00Z"},
            user_timezone="UTC",
        )

    assert match is not None
    assert not match.is_gcal, "a declined Selko row already owns this provider event"
    assert match.match_id == event
    assert match.baseline["review_status"] == declined


def test_a_booking_for_a_rejected_event_reopens_it_for_review(db, factory, spy_commit):
    """Regression: a ticket receipt for a play the user had rejected.

    The user dismissed a school play in a triage pass, then bought tickets three
    weeks later. The receipt matched the rejected event and was recorded as
    provenance, so the play never reached the calendar. Buying tickets reverses
    the user's own decision: the event goes back to the New lane -- and only
    there; it is not approved on their behalf.
    """
    counts, event, _, propose = _save(db, factory, "rejected", _extraction(booking_confirmed=True))

    assert counts == (0, 1)
    decision = spy_commit.decisions[0]
    assert decision["action"] == "update"
    assert decision["event_id"] == event
    assert decision["intent"] == "apply"
    assert decision["fields"] == {"review_status": "pending_review"}, (
        "only the lane changes; nothing is queued for the calendar"
    )
    assert "calendar_action" not in decision["fields"]
    change_set = decision["source"]["change_set"]
    assert change_set["changes"] == [{
        "field": "review_status",
        "before": "rejected",
        "after": "pending_review",
        "reason": "booking confirmed after the user declined",
    }]
    assert decision["source"]["event_snapshot_before"]["review_status"] == "rejected"
    propose.assert_not_called()
    assert factory.row("events", event)["review_status"] == "pending_review"
    assert db.query("SELECT 1 FROM calendar_work_items WHERE event_id = ?", (event,)) == []


def test_a_booking_never_revives_an_organizer_cancelled_event(db, factory, spy_commit):
    """Cancelled is the organizer's word, not the user's: a receipt cannot undo it."""
    counts, event, _, _ = _save(db, factory, "cancelled", _extraction(booking_confirmed=True))

    assert counts == (0, 0)
    assert spy_commit.decisions[0]["intent"] == "record_only"
    assert factory.row("events", event)["review_status"] == "cancelled"


def test_an_announcement_for_a_rejected_event_leaves_it_rejected(db, factory, spy_commit):
    """The other half: a newsletter repeating the event must not nag again."""
    extraction = _extraction()
    assert extraction.booking_confirmed is False
    _, event, _, _ = _save(db, factory, "rejected", extraction)

    assert spy_commit.decisions[0]["intent"] == "record_only"
    assert factory.row("events", event)["review_status"] == "rejected"


def test_extraction_carries_booking_confirmed_from_the_llm_response():
    """The flag must reach save_extracted_events, not stop at the LLM response."""
    from selko.api.schemas.calendar import EventExtractionResponse
    from selko.services import event_processing

    llm_result = EventExtractionResponse(
        events_found=True, events=_extraction().events, booking_confirmed=True
    )
    gw = MagicMock()
    gw.call_validated.return_value = llm_result

    extraction = event_processing.extract_calendar_events(
        gw, "body", {"provider_message_id": "m", "from_email": "a@b.c"}
    )

    assert extraction.booking_confirmed is True
