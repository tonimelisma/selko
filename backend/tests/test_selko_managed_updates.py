"""Updates to events Selko created apply without a second approval.

The user approves an event once. A later email that moves it, renames it or
adds detail is the same event changing, so it is applied and the calendar
entry updated. Only an event the user made in their own calendar (adopted,
with ``google_calendar`` provenance) keeps its change in the Changes lane:
Selko never rewrites a calendar entry the user authored without asking.

Runs on a real database: the match, the provenance read and the commit are the
real ones. Only the LLM (`compare_events`, `propose_event_update`) and the
calendar provider's live read are mocked.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from selko.db.connection import Database
from selko.api.schemas.calendar import CalendarEvent, CalendarEventExtraction
from selko.services.event_diff import EventChangeSet, FieldChange
from selko.services.events import _is_from_users_calendar, save_extracted_events
from tests.event_pipeline import (
    claimed_email,
    future_local,
    gateway,
    lease,
    providers_offline,
    spy_commit,  # noqa: F401  (fixture)
)
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/New_York")


def _iso_local(naive: datetime) -> str:
    return naive.replace(tzinfo=ZONE).isoformat()


def _extraction(start: datetime, end: datetime, **fields) -> CalendarEventExtraction:
    values = {"title": "Team Meeting", "location": "Room B", "description": "Weekly sync"}
    values.update(fields)
    return CalendarEventExtraction(
        email_message_id="msg-update",
        sender_email="organizer@example.com",
        events_found=True,
        events=[CalendarEvent(start_datetime=start, end_datetime=end, **values)],
    )


def _change_set(kind="material_update"):
    return EventChangeSet(
        kind=kind,
        changes=[FieldChange(field="location", before="Room A", after="Room B", reason="moved")],
    )


def _route(db, factory, spy, *, from_users_calendar, kind="material_update", review_status="active"):
    user = factory.user()
    start = future_local()
    event = factory.event(
        user, review_status=review_status, title="Team Meeting",
        start_datetime=_iso_local(start), end_datetime=_iso_local(start + timedelta(hours=1)),
        location="Room A", description="Weekly sync",
    )
    if from_users_calendar:
        factory.event_source(event)  # adopted: google_calendar provenance
    email = claimed_email(factory, user)
    with providers_offline(), \
         patch("selko.services.events.event_processing.compare_events", return_value=event), \
         patch("selko.services.events.event_processing.propose_event_update",
               return_value=_change_set(kind)):
        counts = save_extracted_events(
            db, gateway(), user, email, _extraction(start, start + timedelta(hours=1)),
            **lease(db, email),
        )
    return counts, spy.decisions, event


def test_an_update_to_a_selko_created_event_applies_without_approval(db, factory, spy_commit):
    counts, decisions, event = _route(db, factory, spy_commit, from_users_calendar=False)

    assert counts == (0, 1)
    decision = decisions[0]
    assert decision["intent"] == "apply"
    assert decision["event_id"] == event
    assert decision["fields"]["review_status"] == "active"
    assert decision["fields"]["calendar_action"] == "upsert", "the calendar entry is updated"
    assert decision["fields"]["location"] == "Room B"
    assert decision["source"]["change_set"]["kind"] == "material_update", "History keeps the change"
    # ...and the commit wrote it: the event moved, a calendar upsert is queued,
    # and an applied proposal stays for History and undo.
    assert factory.row("events", event)["location"] == "Room B"
    work = db.query("SELECT action, status FROM calendar_work_items WHERE event_id = ?", (event,))
    assert [(w["action"], w["status"]) for w in work] == [("upsert", "pending")]
    proposals = db.query("SELECT status FROM event_change_proposals WHERE event_id = ?", (event,))
    assert [p["status"] for p in proposals] == ["applied"]


def test_an_update_to_an_event_from_the_users_calendar_waits_for_review(db, factory, spy_commit):
    _, decisions, event = _route(db, factory, spy_commit, from_users_calendar=True)

    decision = decisions[0]
    assert decision["intent"] == "review"
    assert decision["fields"] == {"review_status": "active"}, "the event keeps its values"
    assert factory.row("events", event)["location"] == "Room A"
    assert db.query("SELECT 1 FROM calendar_work_items WHERE event_id = ?", (event,)) == []
    proposals = db.query("SELECT status FROM event_change_proposals WHERE event_id = ?", (event,))
    assert [p["status"] for p in proposals] == ["pending"]


def test_a_cancellation_reading_of_a_selko_event_still_waits_for_review(db, factory, spy_commit):
    """An upsert cannot remove an event; organizer cancellations take their own path."""
    _, decisions, _ = _route(db, factory, spy_commit, from_users_calendar=False, kind="cancellation")

    assert decisions[0]["intent"] == "review"


def test_an_unapproved_event_absorbs_the_update_and_stays_in_new(db, factory, spy_commit):
    with patch("selko.services.events._is_from_users_calendar",
               wraps=_is_from_users_calendar) as provenance:
        _, decisions, event = _route(
            db, factory, spy_commit, from_users_calendar=False, review_status="pending_review"
        )

    assert decisions[0]["intent"] == "apply"
    assert decisions[0]["fields"]["review_status"] == "pending_review"
    assert "calendar_action" not in decisions[0]["fields"]
    provenance.assert_not_called()
    row = factory.row("events", event)
    assert (row["review_status"], row["location"]) == ("pending_review", "Room B")
    assert db.query("SELECT 1 FROM calendar_work_items WHERE event_id = ?", (event,)) == []


@pytest.mark.parametrize("adopted, expected", [(True, True), (False, False)])
def test_provenance_reads_google_calendar_sources(db, factory, adopted, expected):
    user = factory.user()
    event = factory.event(user)
    factory.event_source(event, factory.email(user))  # email provenance never counts
    if adopted:
        factory.event_source(event)

    assert _is_from_users_calendar(db, event) is expected


def test_provenance_is_read_per_event(db, factory):
    user = factory.user()
    adopted, created = factory.event(user), factory.event(user)
    factory.event_source(adopted)

    assert _is_from_users_calendar(db, created) is False


def test_a_failed_provenance_lookup_keeps_the_change_for_review(tmp_path):
    # A database file with no schema: every read fails, as a broken one would.
    broken = Database(tmp_path / "unmigrated.db")
    try:
        assert _is_from_users_calendar(broken, "00000000-0000-0000-0000-000000000001") is True
    finally:
        broken.close()


# Production, Nov 18: "Walnut Creek on Ice" was stored as a span from Nov 20
# to Jan 18. A later "The rink opens this Friday" email moved only the start
# to 16:00, the stored Jan 18 end survived, and the auto-applied update put a
# timed two-month event on the user's calendar.
_YEAR = datetime.now().year + 1


def _season_route(db, factory, spy, email_start, email_end, change_start):
    user = factory.user()
    stored_start = datetime(_YEAR, 11, 20, 8, 0)
    event = factory.event(
        user, review_status="active", title="Walnut Creek on Ice Opens",
        start_datetime=_iso_local(stored_start),
        end_datetime=_iso_local(datetime(_YEAR + 1, 1, 18, 17, 0)),
        location="Civic Park", description="Season runs through January 18.", importance="fyi",
    )
    stored = factory.row("events", event)
    email = claimed_email(factory, user)
    change_set = EventChangeSet(
        kind="material_update",
        changes=[FieldChange(
            field="start_datetime", before=stored["start_datetime"], after=change_start,
            reason="opening time stated",
        )],
    )
    extraction = _extraction(
        email_start, email_end, title="Walnut Creek on Ice Opens", location="Civic Park",
        description="Season runs through January 18.",
    )
    with providers_offline(), \
         patch("selko.services.events.event_processing.compare_events", return_value=event), \
         patch("selko.services.events.event_processing.propose_event_update",
               return_value=change_set):
        save_extracted_events(db, gateway(), user, email, extraction, **lease(db, email))
    return spy.decisions[0]


def test_moving_the_start_of_a_season_span_does_not_apply_a_two_month_timed_event(
    db, factory, spy_commit
):
    opening = datetime(_YEAR, 11, 20, 16, 0)
    decision = _season_route(
        db, factory, spy_commit,
        email_start=opening,
        email_end=opening + timedelta(hours=5),
        change_start=opening.isoformat(),
    )

    fields = decision["fields"]
    start = datetime.fromisoformat(fields["start_datetime"])
    end = datetime.fromisoformat(fields["end_datetime"])
    assert fields["all_day"] is False
    assert end - start == timedelta(hours=5), "the end follows the email, not the stored Jan 18"
    changed = {c["field"] for c in decision["source"]["change_set"]["changes"]}
    assert "end_datetime" in changed, "History and undo see the end change too"


def test_an_email_that_itself_states_a_multi_day_timed_event_is_left_alone(db, factory, spy_commit):
    start = datetime(_YEAR, 11, 20, 9, 0)
    decision = _season_route(
        db, factory, spy_commit,
        email_start=start,
        email_end=start + timedelta(days=2, hours=8),
        change_start=start.isoformat(),
    )

    changed = {c["field"] for c in decision["source"]["change_set"]["changes"]}
    assert changed == {"start_datetime"}
