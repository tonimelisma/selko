"""The extraction commit honours its decision intent, on a real SQLite database.

Every test here executes ``commit_email_extraction`` itself. That is the whole
point: the Changes lane was silently auto-applied for the entire life of #332
because the unit suite stubbed this function and the proposal integration suite
INSERTed proposal rows directly, so nothing had ever run it with a change_set.
The two service-level tests run ``save_extracted_events`` end to end: the real
match, the real provenance read and the real commit; only the LLM is mocked.
"""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from selko.db import calendar_work as db_calendar_work
from selko.db import emails as db_emails
from selko.db import errors
from selko.db import events as db_events
from tests.event_pipeline import gateway, providers_offline

DAY = "2026-09-14"


def _window() -> tuple[str, str]:
    y, m, d = (int(p) for p in DAY.split("-"))
    return f"{DAY}T00:00:00Z", f"{(date(y, m, d) + timedelta(days=1)).isoformat()}T00:00:00Z"


def _change_set() -> dict:
    return {"kind": "material_update", "changes": [{"field": "location", "before": "Room A", "after": "Room B"}]}


def _snapshot() -> dict:
    return {
        "title": "Standup",
        "start_datetime": f"{DAY}T10:00:00Z",
        "end_datetime": f"{DAY}T11:00:00Z",
        "all_day": False,
        "location": "Room A",
        "description": None,
        "importance": "action_required",
        "review_status": "active",
    }


def _claim(db, factory, user_id) -> tuple[str, str, int]:
    """Insert an email and claim it: (id, worker, generation)."""
    email_id = factory.email(user_id, subject="intent test")
    worker = f"intent-{email_id}"
    row = db_emails.claim_unprocessed_email(db, worker, 300)
    assert row["id"] == email_id
    return email_id, worker, row["lock_generation"]


def _event(factory, user_id, review_status: str, day: str = DAY) -> str:
    return factory.event(
        user_id, review_status=review_status, title="Standup",
        start_datetime=f"{day}T10:00:00.000000Z", end_datetime=f"{day}T11:00:00.000000Z",
        location="Room A", importance="action_required",
    )


def _decision(db, user_id, email_id, event_id, **overrides) -> dict:
    window = _window()
    decision = {
        "action": "update",
        "event_id": event_id,
        "window_start": window[0],
        "window_end": window[1],
        "expected_fingerprint": db_events.band_fingerprint(db, user_id, *window),
        "hints": [],
        "source": {"email_id": email_id, "extracted_data": {}},
    }
    decision.update(overrides)
    return decision


def _change_source(email_id) -> dict:
    return {"email_id": email_id, "extracted_data": {}, "source_type": "update",
            "event_snapshot_before": _snapshot(), "change_set": _change_set()}


def _commit(db, email_id, worker, generation, decision: dict) -> dict:
    return db_events.commit_email_extraction(db, email_id, worker, generation, [decision], "processed")


def _proposals(db, event_id) -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT status, kind FROM event_change_proposals WHERE event_id = ? ORDER BY created_at", (event_id,))]


def _work_items(db, event_id) -> list[dict]:
    return [db.schema.decode("calendar_work_items", r) for r in db.query(
        "SELECT action, status, desired_event FROM calendar_work_items WHERE event_id = ? ORDER BY generation",
        (event_id,))]


def _event_row(factory, event_id) -> dict:
    row = factory.row("events", event_id)
    return {"review_status": row["review_status"], "title": row["title"], "location": row["location"]}


# --- the four intents ----------------------------------------------------


def test_review_intent_holds_the_change_and_writes_no_calendar_work(db, factory):
    """The Changes lane: a pending proposal, an untouched event, no provider write."""
    user = factory.user()
    email_id, worker, generation = _claim(db, factory, user)
    event_id = _event(factory, user, "active")

    result = _commit(db, email_id, worker, generation, _decision(
        db, user, email_id, event_id, intent="review", fields={"review_status": "active"},
        source=_change_source(email_id),
    ))

    assert result["applied"] == 1
    assert [p["status"] for p in _proposals(db, event_id)] == ["pending"], (
        "a change held for review must produce a pending proposal"
    )
    event = _event_row(factory, event_id)
    assert event["review_status"] == "active"
    assert event["location"] == "Room A", "the proposal owns the change, not the event"
    assert _work_items(db, event_id) == [], "nothing may reach the user's calendar before they accept"


def test_apply_intent_applies_the_change_and_queues_calendar_work(db, factory):
    user = factory.user()
    email_id, worker, generation = _claim(db, factory, user)
    event_id = _event(factory, user, "active")

    _commit(db, email_id, worker, generation, _decision(
        db, user, email_id, event_id,
        intent="apply",
        fields={
            "review_status": "active", "calendar_action": "upsert", "title": "Standup",
            "start_datetime": f"{DAY}T10:00:00Z", "end_datetime": f"{DAY}T11:00:00Z", "location": "Room B",
        },
        source=_change_source(email_id),
    ))

    assert [p["status"] for p in _proposals(db, event_id)] == ["applied"]
    assert _event_row(factory, event_id)["location"] == "Room B"
    items = _work_items(db, event_id)
    assert [item["action"] for item in items] == ["upsert"]
    assert items[0]["desired_event"]["title"] == "Standup", (
        "the queued payload must carry real values, never a NULL-filled object"
    )


def test_apply_intent_on_a_new_lane_event_queues_no_calendar_work(db, factory):
    """Absorbing newer information into an unapproved event is not a delivery."""
    user = factory.user()
    email_id, worker, generation = _claim(db, factory, user)
    event_id = _event(factory, user, "pending_review")

    _commit(db, email_id, worker, generation, _decision(
        db, user, email_id, event_id, intent="apply",
        fields={"review_status": "pending_review", "location": "Room B"},
        source=_change_source(email_id),
    ))

    event = _event_row(factory, event_id)
    assert event["review_status"] == "pending_review", "it stays in the New lane"
    assert event["location"] == "Room B"
    assert _work_items(db, event_id) == []


@pytest.mark.parametrize("declined", ["rejected", "cancelled"])
def test_record_only_leaves_a_declined_event_untouched(db, factory, declined):
    """review-queue-integrity 8.2: record the match, change nothing."""
    user = factory.user()
    email_id, worker, generation = _claim(db, factory, user)
    event_id = _event(factory, user, declined)

    _commit(db, email_id, worker, generation, _decision(
        db, user, email_id, event_id, intent="record_only", fields={},
        source={"email_id": email_id, "extracted_data": {}, "source_type": "update"},
    ))

    event = _event_row(factory, event_id)
    assert event["review_status"] == declined, "a declined event is never revived"
    assert event["location"] == "Room A"
    assert _proposals(db, event_id) == []
    assert _work_items(db, event_id) == []
    # Provenance still lands: that is what keeps the identity match working, and
    # therefore what keeps the decision terminal instead of producing duplicates.
    assert db.query_one(
        "SELECT count(*) FROM event_sources WHERE event_id = ? AND email_id = ?", (event_id, email_id)
    )[0] == 1


def _future_day() -> datetime:
    return (datetime.now() + timedelta(days=30)).replace(hour=10, minute=0, second=0, microsecond=0)


def test_a_booking_reopens_a_rejected_event_into_the_new_lane(db, factory):
    """Regression: a ticket receipt for a play the user had rejected.

    The decision ``save_extracted_events`` builds goes through the real commit:
    the event returns to pending_review, an applied proposal records why, and
    nothing is queued for the calendar.
    """
    from selko.api.schemas.calendar import CalendarEvent, CalendarEventExtraction
    from selko.services.events import save_extracted_events

    user = factory.user()
    factory._insert("user_calendar_settings", {"user_id": user, "timezone": "UTC"})
    start = _future_day()
    day = start.date().isoformat()
    event_id = _event(factory, user, "rejected", day=day)
    email_id, worker, generation = _claim(db, factory, user)
    extraction = CalendarEventExtraction(
        email_message_id="receipt", sender_email="tickets@example.com", events_found=True,
        booking_confirmed=True,
        events=[CalendarEvent(title="Standup", start_datetime=start, description="tickets")],
    )

    with providers_offline(), \
         patch("selko.services.events.event_processing.compare_events", return_value=event_id):
        assert save_extracted_events(
            db, gateway(), user, email_id, extraction, locked_by=worker, lock_generation=generation,
        ) == (0, 1)

    event = _event_row(factory, event_id)
    assert event["review_status"] == "pending_review", "back in the New lane"
    assert event["location"] == "Room A", "only the lane changed"
    assert _work_items(db, event_id) == [], "never straight to the calendar"
    assert [(p["status"], p["kind"]) for p in _proposals(db, event_id)] == [("applied", "material_update")]


# --- fail-closed ---------------------------------------------------------


def test_a_decision_without_an_intent_is_refused(db, factory):
    """The regression itself: silence must never mean 'apply and deliver'."""
    user = factory.user()
    email_id, worker, generation = _claim(db, factory, user)
    event_id = _event(factory, user, "active")

    decision = _decision(db, user, email_id, event_id, fields={}, source=_change_source(email_id))
    with pytest.raises(errors.InvalidArgument, match="known intent"):
        _commit(db, email_id, worker, generation, decision)
    assert _work_items(db, event_id) == []


def test_a_decision_without_a_review_status_is_refused(db, factory):
    user = factory.user()
    email_id, worker, generation = _claim(db, factory, user)
    event_id = _event(factory, user, "active")

    decision = _decision(db, user, email_id, event_id, intent="no_change", fields={})
    with pytest.raises(errors.InvalidArgument, match="explicit review_status"):
        _commit(db, email_id, worker, generation, decision)


def test_review_intent_requires_an_active_event(db, factory):
    """A pending proposal requires review_status 'active'; say so, don't guess."""
    user = factory.user()
    email_id, worker, generation = _claim(db, factory, user)
    event_id = _event(factory, user, "active")

    decision = _decision(db, user, email_id, event_id, intent="review",
                         fields={"review_status": "pending_review"}, source=_change_source(email_id))
    with pytest.raises(errors.InvalidArgument, match="requires review_status active"):
        _commit(db, email_id, worker, generation, decision)


def test_no_change_intent_cannot_carry_a_change_set(db, factory):
    user = factory.user()
    email_id, worker, generation = _claim(db, factory, user)
    event_id = _event(factory, user, "active")

    decision = _decision(db, user, email_id, event_id, intent="no_change",
                         fields={"review_status": "active"}, source=_change_source(email_id))
    with pytest.raises(errors.InvalidArgument, match="cannot carry a change_set"):
        _commit(db, email_id, worker, generation, decision)


@pytest.mark.parametrize("declined", ["rejected", "cancelled"])
def test_calendar_upsert_is_refused_for_a_declined_event(db, factory, declined):
    """The queue helper no longer resurrects; it fails closed."""
    user = factory.user()
    event_id = _event(factory, user, declined)
    with pytest.raises(errors.InvalidArgument, match="cannot queue calendar upsert"):
        db_calendar_work.enqueue_calendar_work(db, user, event_id, "upsert", {"title": "Standup"})
    assert _event_row(factory, event_id)["review_status"] == declined


def test_queueing_calendar_work_does_not_change_the_review_decision(db, factory):
    """events.review_status owns the user decision; the queue helper does not.

    The helper used to promote pending_review/rejected/cancelled to 'active' on
    every call. One caller depended on that side effect and two others undid it
    immediately afterwards, which is how a declined event could be revived by
    something as unrelated as queueing a calendar write.
    """
    user = factory.user()
    event_id = _event(factory, user, "pending_review")
    db_calendar_work.enqueue_calendar_work(db, user, event_id, "upsert", {"title": "Standup"})
    assert _event_row(factory, event_id)["review_status"] == "pending_review"
    assert [item["action"] for item in _work_items(db, event_id)] == ["upsert"]


@pytest.mark.parametrize("adopted_from_calendar", [False, True])
def test_an_update_applies_to_a_selko_event_and_waits_on_a_calendar_one(db, factory, adopted_from_calendar):
    """Provenance is read from real rows and the decision goes through the real commit.

    A Selko-created event (email provenance only) takes the update and queues
    calendar work; an event adopted from the user's own calendar keeps its
    values and gets a pending proposal instead.
    """
    from selko.api.schemas.calendar import CalendarEvent, CalendarEventExtraction
    from selko.services.event_diff import EventChangeSet, FieldChange
    from selko.services.events import save_extracted_events

    user = factory.user()
    factory._insert("user_calendar_settings", {"user_id": user, "timezone": "UTC"})
    start = _future_day()
    event_id = _event(factory, user, "active", day=start.date().isoformat())
    factory.event_source(event_id, factory.email(user, processing_status="processed"),
                         source_type="new_invitation")
    if adopted_from_calendar:
        factory.event_source(event_id, source_type="unknown")
    email_id, worker, generation = _claim(db, factory, user)
    extraction = CalendarEventExtraction(
        email_message_id="update", sender_email="organizer@example.com", events_found=True,
        events=[CalendarEvent(title="Standup", start_datetime=start, end_datetime=start + timedelta(hours=1),
                              location="Room B", description="moved")],
    )
    change_set = EventChangeSet(kind="material_update", changes=[
        FieldChange(field="location", before="Room A", after="Room B", reason="moved")])

    with providers_offline(), \
         patch("selko.services.events.event_processing.compare_events", return_value=event_id), \
         patch("selko.services.events.event_processing.propose_event_update", return_value=change_set):
        save_extracted_events(db, gateway(), user, email_id, extraction,
                              locked_by=worker, lock_generation=generation)

    event = _event_row(factory, event_id)
    proposals = _proposals(db, event_id)
    work = _work_items(db, event_id)
    if adopted_from_calendar:
        assert event["location"] == "Room A", "the user's own entry is not rewritten"
        assert [p["status"] for p in proposals] == ["pending"]
        assert work == []
    else:
        assert event["location"] == "Room B"
        assert [p["status"] for p in proposals] == ["applied"]
        assert [(w["action"], w["desired_event"]["location"]) for w in work] == [("upsert", "Room B")]
