"""A calendar entry that arrives after its email must still retire the duplicate.

Production, 2026-10-31: a "You're checked in at Supercuts!" email was extracted
at 23:05Z into a pending "Supercuts Appointment" at 17:40Z the next day. The
user's own "Supercuts" entry at 17:40Z sat on an imported calendar that Google
refreshed later; it reached the mirror at 00:30Z. Dedup had already run, and
nothing ran again, so both stayed visible.

Runs on a real database; only the LLM comparison is mocked.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

from selko.services import events

SUPERCUTS_ENTRY = {
    "provider_event_id": "imported-supercuts",
    "title": "Supercuts",
    "start_at": "2026-11-01T17:40:00+00:00",
    "end_at": "2026-11-01T18:00:00+00:00",
    "location": "3000 DANVILLE BLVD STE C, ALAMO, CA 94507",
    "origin": "external",
    "status": "confirmed",
    "deleted_at": None,
}


@pytest.fixture
def supercuts(db, factory):
    """A pending event from a check-in email whose only event it was."""
    user = factory.user()
    factory._insert("user_calendar_settings", {"user_id": user, "timezone": "America/Los_Angeles"})
    email = factory.email(
        user, subject="You're checked in at Supercuts!", processing_status="processed",
        processing_outcome="event_created",
        processing_result={"num_new": 1, "num_events": 1, "num_updated": 0},
    )
    event = factory.event(
        user, title="Supercuts Appointment",
        start_datetime="2026-11-01T17:40:00.000000Z", end_datetime="2026-11-01T18:40:00.000000Z",
        location="3000 DANVILLE BLVD STE C, ALAMO, California 94507",
        description="Haircut appointment at Supercuts.",
    )
    factory.event_source(event, email)
    return user, event, email


def _retire(db, user, arrived, matched_id=None, *, side_effect=None):
    gateway_factory = MagicMock()
    with patch.object(events.event_processing, "compare_events",
                      return_value=matched_id, side_effect=side_effect) as compare:
        retired = events.retire_pending_already_on_calendar(db, user, arrived, gateway_factory)
    return retired, compare, gateway_factory


def test_the_supercuts_duplicate_leaves_new_when_its_calendar_entry_arrives(db, factory, supercuts):
    user, event, email = supercuts

    retired, compare, _ = _retire(db, user, [SUPERCUTS_ENTRY], "gcal:imported-supercuts")

    assert retired == 1
    # The end times differ (the model guessed an hour; the entry is 20 min), so
    # an exact start/end match would have missed it. Start is the gate, the
    # comparison decides -- told the user's own zone.
    compare.assert_called_once()
    assert compare.call_args.kwargs["user_timezone"] == "America/Los_Angeles"
    assert factory.row("events", event)["review_status"] == "rejected"
    relabelled = factory.row("emails", email)
    assert relabelled["processing_outcome"] == "event_matched"
    assert "Supercuts" in relabelled["processing_explanation"]


def test_a_different_start_minute_costs_no_llm_call(db, factory, supercuts):
    user, event, _ = supercuts
    elsewhere = {**SUPERCUTS_ENTRY, "start_at": "2026-11-01T17:45:00+00:00"}

    retired, compare, gateway_factory = _retire(db, user, [elsewhere], "gcal:imported-supercuts")

    assert retired == 0
    compare.assert_not_called()
    gateway_factory.assert_not_called()
    assert factory.row("events", event)["review_status"] == "pending_review"


def test_a_different_event_at_the_same_minute_stays_in_new(db, factory, supercuts):
    user, event, email = supercuts
    dentist = {**SUPERCUTS_ENTRY, "provider_event_id": "dentist", "title": "Dentist"}

    retired, compare, _ = _retire(db, user, [dentist], None)

    assert retired == 0
    compare.assert_called_once()
    assert factory.row("events", event)["review_status"] == "pending_review"
    assert factory.row("emails", email)["processing_outcome"] == "event_created"


def test_selko_s_own_and_removed_entries_are_not_evidence(db, factory, supercuts):
    user, event, _ = supercuts
    arrived = [
        {**SUPERCUTS_ENTRY, "origin": "selko_created"},
        {**SUPERCUTS_ENTRY, "deleted_at": "2026-11-01T00:00:00+00:00", "status": "cancelled"},
    ]

    with patch.object(events.db_events, "pending_in_window",
                      wraps=events.db_events.pending_in_window) as read:
        retired, compare, _ = _retire(db, user, arrived, "gcal:imported-supercuts")

    assert retired == 0
    compare.assert_not_called()
    read.assert_not_called()  # nothing qualified, so nothing is queried
    assert factory.row("events", event)["review_status"] == "pending_review"


def test_an_event_the_user_approved_meanwhile_is_left_alone(db, factory, supercuts):
    """The retirement is a compare-and-set on pending_review."""
    user, event, email = supercuts

    def approve_then_match(*_args, **_kwargs):
        # The user approves while the comparison runs.
        with db.write() as tx:
            tx.execute("UPDATE events SET review_status = 'active', updated_at = ? WHERE id = ?",
                       (tx.now_text, event))
        return "gcal:imported-supercuts"

    retired, _, _ = _retire(db, user, [SUPERCUTS_ENTRY], side_effect=approve_then_match)

    assert retired == 0
    assert factory.row("events", event)["review_status"] == "active"
    assert factory.row("emails", email)["processing_outcome"] == "event_created", (
        "History must not claim a match that did not apply"
    )


def test_an_email_that_also_created_other_events_keeps_its_outcome(db, factory, supercuts):
    user, event, email = supercuts
    with db.write() as tx:
        tx.execute("UPDATE emails SET processing_result = ? WHERE id = ?",
                   ('{"num_events":2,"num_new":2,"num_updated":0}', email))

    retired, _, _ = _retire(db, user, [SUPERCUTS_ENTRY], "gcal:imported-supercuts")

    assert retired == 1
    assert factory.row("events", event)["review_status"] == "rejected"
    assert factory.row("emails", email)["processing_outcome"] == "event_created"


def test_a_failed_comparison_retires_nothing(db, factory, supercuts):
    user, event, _ = supercuts

    retired, _, _ = _retire(db, user, [SUPERCUTS_ENTRY], side_effect=RuntimeError("down"))

    assert retired == 0
    assert factory.row("events", event)["review_status"] == "pending_review"


def test_the_mirror_hands_back_what_each_pass_wrote(db):
    from selko.services import calendar_mirror

    def fake_sync(client, user_id, integration_id, calendar_id, **kwargs):
        return {"entries": 1, "full_resync": False, "has_sync_token": True,
                "arrived": [{"provider_event_id": calendar_id}]}

    with patch.object(calendar_mirror, "list_provider_calendars",
                      return_value=[{"id": "me@example.com"}, {"id": "imported@example.com"}]), \
            patch.object(calendar_mirror, "sync_calendar", side_effect=fake_sync):
        totals = calendar_mirror.sync_all_calendars(db, "u1", "i1")

    assert [e["provider_event_id"] for e in totals["arrived"]] == [
        "me@example.com", "imported@example.com",
    ]


def test_the_runtime_retires_duplicates_after_every_mirror_sync():
    """A function nobody calls has not shipped (CLAUDE.md, call-site rule)."""
    from selko.workers.ingestion_runtime import IngestionRuntime

    loop = inspect.getsource(IngestionRuntime._calendar_mirror_floor)
    assert "retire_pending_already_on_calendar" in loop
    assert loop.index("sync_all_calendars") < loop.index("retire_pending_already_on_calendar")
