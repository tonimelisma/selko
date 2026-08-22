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
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from selko.api.schemas.calendar import CalendarEvent, CalendarEventExtraction
from selko.services.events import EventMatch, find_matching_event, save_extracted_events


def _extraction():
    future = datetime.now() + timedelta(days=30)
    return CalendarEventExtraction(
        email_message_id="msg-declined",
        email_date=datetime(2026, 4, 9, 10, 0),
        sender_email="sender@example.com",
        events_found=True,
        events=[CalendarEvent(
            title="Team Meeting",
            start_datetime=future.replace(hour=14, minute=0, second=0, microsecond=0),
            end_datetime=future.replace(hour=15, minute=0, second=0, microsecond=0),
            location="Room A",
            description="Weekly sync",
        )],
    )


@pytest.fixture(autouse=True)
def stub_commit(monkeypatch):
    def fake_commit(client, email_id, locked_by, lock_generation, decisions, terminal="processed"):
        client._extraction_decisions = decisions
        return {"fenced": False, "applied": len(decisions), "event_ids": []}

    monkeypatch.setattr("selko.services.events._commit_email_extraction", fake_commit)


@pytest.mark.parametrize("declined", ["rejected", "cancelled"])
def test_an_update_matching_a_declined_event_records_only(declined):
    match = EventMatch(
        match_id="event-declined",
        baseline={"title": "Team Meeting", "review_status": declined},
    )
    client, gateway = MagicMock(), MagicMock()

    with patch("selko.services.events.find_matching_event", return_value=match), \
         patch("selko.services.events.event_processing.propose_event_update") as propose:
        num_new, num_updated = save_extracted_events(
            client, gateway, "user-1", "email-1", _extraction()
        )

    assert (num_new, num_updated) == (0, 0), "a declined match changes nothing"
    decision = client._extraction_decisions[0]
    assert decision["intent"] == "record_only"
    assert decision["fields"] == {}
    assert "change_set" not in decision["source"]
    # No LLM call for a change the user will never see.
    propose.assert_not_called()


@pytest.mark.parametrize("declined", ["rejected", "cancelled"])
def test_a_cancellation_matching_a_declined_event_records_only(declined):
    """Cancelling a declined event would revive it and queue a provider write."""
    match = EventMatch(
        match_id="event-declined",
        baseline={"title": "Team Meeting", "review_status": declined},
    )
    client, gateway = MagicMock(), MagicMock()

    with patch("selko.services.events.find_matching_event", return_value=match):
        save_extracted_events(
            client, gateway, "user-1", "email-1", _extraction(),
            cancellation_mode=True,
        )

    decision = client._extraction_decisions[0]
    assert decision["intent"] == "record_only"
    assert decision["fields"] == {}


@pytest.mark.parametrize("declined", ["rejected", "cancelled"])
def test_a_declined_adopted_event_is_matched_not_adopted_again(declined):
    """The provider-event lookup must see declined rows.

    An event adopted from the user's own Google Calendar is not written back
    until they accept, so it carries no selko_event_id and the calendar
    read-back keeps matching it. If the lookup that maps that provider event to
    its existing Selko row skips declined rows, every later email adopts it
    again -- a duplicate of something the user rejected.
    """
    client, gateway = MagicMock(), MagicMock()
    selected = client.table.return_value.select.return_value
    # Local-day candidate window: no local matches by start_datetime.
    selected.eq.return_value.gte.return_value.lt.return_value.execute.return_value = (
        MagicMock(data=[])
    )
    # The provider-event lookup, which must find the declined row.
    selected.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[{
            "id": "event-declined",
            "title": "Team Meeting",
            "start_datetime": "2026-05-09T14:00:00Z",
            "end_datetime": "2026-05-09T15:00:00Z",
            "all_day": False,
            "location": "Room A",
            "description": None,
            "importance": "action_required",
            "review_status": declined,
        }])
    )

    with patch("selko.services.events.get_user_timezone", return_value="UTC"), \
         patch(
             "selko.services.events.calendars.fetch_calendar_events_for_date_range",
             return_value=[{"id": "abc-123", "summary": "Team Meeting",
                            "start": {"dateTime": "2026-05-09T14:00:00Z"},
                            "end": {"dateTime": "2026-05-09T15:00:00Z"}}],
         ), \
         patch(
             "selko.services.events.event_processing.compare_events",
             return_value="gcal:abc-123",
         ):
        match = find_matching_event(
            client, gateway, "user-1",
            {"title": "Team Meeting", "start_datetime": "2026-05-09T14:00:00Z",
             "end_datetime": "2026-05-09T15:00:00Z"},
            user_timezone="UTC",
        )

    assert match is not None
    assert not match.is_gcal, "a declined Selko row already owns this provider event"
    assert match.match_id == "event-declined"
    assert match.baseline["review_status"] == declined
