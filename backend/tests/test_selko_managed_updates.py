"""Updates to events Selko created apply without a second approval.

The user approves an event once. A later email that moves it, renames it or
adds detail is the same event changing, so it is applied and the calendar
entry updated. Only an event the user made in their own calendar (adopted,
with ``google_calendar`` provenance) keeps its change in the Changes lane:
Selko never rewrites a calendar entry the user authored without asking.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from selko.api.schemas.calendar import CalendarEvent, CalendarEventExtraction
from selko.services.event_diff import EventChangeSet, FieldChange
from selko.services.events import (
    EventMatch,
    _is_from_users_calendar,
    save_extracted_events,
)


BASELINE = {
    "title": "Team Meeting",
    "start_datetime": "2026-12-09T14:00:00+00:00",
    "end_datetime": "2026-12-09T15:00:00+00:00",
    "all_day": False,
    "location": "Room A",
    "description": "Weekly sync",
    "importance": "action_required",
    "review_status": "active",
}


def _extraction():
    future = datetime.now() + timedelta(days=30)
    return CalendarEventExtraction(
        email_message_id="msg-update",
        sender_email="organizer@example.com",
        events_found=True,
        events=[CalendarEvent(
            title="Team Meeting",
            start_datetime=future.replace(hour=14, minute=0, second=0, microsecond=0),
            end_datetime=future.replace(hour=15, minute=0, second=0, microsecond=0),
            location="Room B",
            description="Weekly sync",
        )],
    )


def _change_set(kind="material_update"):
    return EventChangeSet(
        kind=kind,
        changes=[FieldChange(field="location", before="Room A", after="Room B", reason="moved")],
    )


def _route(*, from_users_calendar, kind="material_update", review_status="active"):
    captured: list[dict] = []

    def fake_commit(client, email_id, locked_by, lock_generation, decisions, terminal="processed"):
        captured.extend(decisions)
        return {"fenced": False, "applied": len(decisions), "event_ids": []}

    match = EventMatch(match_id="event-1", baseline={**BASELINE, "review_status": review_status})
    with patch("selko.services.events.find_matching_event", return_value=match), \
         patch("selko.services.events._commit_email_extraction", side_effect=fake_commit), \
         patch("selko.services.events._fetch_baseline_info_date", return_value=None), \
         patch("selko.services.events.event_processing.propose_event_update",
               return_value=_change_set(kind)), \
         patch("selko.services.events._is_from_users_calendar",
               return_value=from_users_calendar) as provenance:
        counts = save_extracted_events(MagicMock(), MagicMock(), "user-1", "email-1", _extraction())
    return counts, captured, provenance


def test_an_update_to_a_selko_created_event_applies_without_approval():
    counts, decisions, provenance = _route(from_users_calendar=False)

    assert counts == (0, 1)
    decision = decisions[0]
    assert decision["intent"] == "apply"
    assert decision["fields"]["review_status"] == "active"
    assert decision["fields"]["calendar_action"] == "upsert", "the calendar entry is updated"
    assert decision["fields"]["location"] == "Room B"
    assert decision["source"]["change_set"]["kind"] == "material_update", "History keeps the change"
    provenance.assert_called_once()
    assert provenance.call_args.args[1] == "event-1"


def test_an_update_to_an_event_from_the_users_calendar_waits_for_review():
    _, decisions, _ = _route(from_users_calendar=True)

    decision = decisions[0]
    assert decision["intent"] == "review"
    assert decision["fields"] == {"review_status": "active"}, "the event keeps its values"


def test_a_cancellation_reading_of_a_selko_event_still_waits_for_review():
    """An upsert cannot remove an event; organizer cancellations take their own path."""
    _, decisions, _ = _route(from_users_calendar=False, kind="cancellation")

    assert decisions[0]["intent"] == "review"


def test_an_unapproved_event_absorbs_the_update_and_stays_in_new():
    _, decisions, provenance = _route(from_users_calendar=False, review_status="pending_review")

    assert decisions[0]["intent"] == "apply"
    assert decisions[0]["fields"]["review_status"] == "pending_review"
    assert "calendar_action" not in decisions[0]["fields"]
    provenance.assert_not_called()


@pytest.mark.parametrize("rows, expected", [([{"id": "s1"}], True), ([], False)])
def test_provenance_reads_google_calendar_sources(rows, expected):
    client = MagicMock()
    query = client.table.return_value.select.return_value
    query.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=rows)
    )

    assert _is_from_users_calendar(client, "event-1") is expected
    client.table.assert_called_once_with("event_sources")
    query.eq.assert_called_once_with("event_id", "event-1")
    query.eq.return_value.eq.assert_called_once_with("source_origin", "google_calendar")


def test_a_failed_provenance_lookup_keeps_the_change_for_review():
    client = MagicMock()
    client.table.side_effect = RuntimeError("network down")

    assert _is_from_users_calendar(client, "event-1") is True
