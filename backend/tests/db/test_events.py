"""`selko.db.events` against a real SQLite database.

Ports the assertions of integration/test_integration_fenced_event_commit.py,
test_integration_extraction_intent.py, test_integration_event_identity.py,
test_integration_identity_mirror_fence.py, test_integration_hint_upsert.py and
test_integration_late_calendar_match.py, run through the SQLite ports of
``commit_email_extraction``, ``set_event_review_status`` and the event reads.
No database call is mocked.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from hashlib import md5
from unittest.mock import MagicMock, patch

import pytest
from selko.db import errors
from selko.db import events as db_events
from selko.db.codec import new_id
from selko.services.resolution_fingerprint import candidate_fingerprint

DAY = "2026-09-14"
EMPTY = md5(b"").hexdigest()


def _window(day: str = DAY) -> tuple[str, str]:
    y, m, d = (int(p) for p in day.split("-"))
    return f"{day}T00:00:00Z", f"{(date(y, m, d) + timedelta(days=1)).isoformat()}T00:00:00Z"


def _claimed_email(factory, user_id: str, worker: str = "worker-1", generation: int = 1, **extra) -> str:
    return factory.email(user_id, processing_status="processing", locked_by=worker,
                         locked_until="2099-01-01T00:00:00.000000Z", lock_generation=generation, **extra)


def _create(email_id: str, title: str, day: str = DAY, fingerprint: str = EMPTY, **fields) -> dict:
    window = _window(day)
    return {
        "action": "create", "event_id": None, "intent": "no_change",
        "window_start": window[0], "window_end": window[1], "expected_fingerprint": fingerprint,
        "fields": {"title": title, "start_datetime": f"{day}T10:00:00Z",
                   "end_datetime": f"{day}T11:00:00Z", "review_status": "pending_review", **fields},
        "source": {"email_id": email_id, "extracted_data": {}},
    }


def _commit(db, email_id: str, decisions: list[dict], worker: str = "worker-1", generation: int = 1,
            terminal: str = "processed") -> dict:
    return db_events.commit_email_extraction(db, email_id, worker, generation, decisions, terminal)


def _active_event(factory, user_id: str, review_status: str = "active", **extra) -> str:
    values = {"title": "Standup", "start_datetime": f"{DAY}T10:00:00.000000Z",
              "end_datetime": f"{DAY}T11:00:00.000000Z", "location": "Room A",
              "importance": "action_required"}
    values.update(extra)
    return factory.event(user_id, review_status=review_status, **values)


def _change_set() -> dict:
    return {"kind": "material_update", "changes": [{"field": "location", "before": "Room A", "after": "Room B"}]}


def _snapshot() -> dict:
    return {"title": "Standup", "start_datetime": f"{DAY}T10:00:00Z", "end_datetime": f"{DAY}T11:00:00Z",
            "all_day": False, "location": "Room A", "description": None,
            "importance": "action_required", "review_status": "active"}


def _update(db, user_id: str, email_id: str, event_id: str, **overrides) -> dict:
    window = _window()
    decision = {
        "action": "update", "event_id": event_id, "window_start": window[0], "window_end": window[1],
        "expected_fingerprint": db_events.band_fingerprint(db, user_id, *window),
        "hints": [], "source": {"email_id": email_id, "extracted_data": {}},
    }
    decision.update(overrides)
    return decision


def _change_source(email_id: str) -> dict:
    return {"email_id": email_id, "extracted_data": {}, "source_type": "update",
            "event_snapshot_before": _snapshot(), "change_set": _change_set()}


def _count(db, sql: str, params=()) -> int:
    return db.query_one(sql, params)[0]


def _work(db, event_id: str) -> list[dict]:
    rows = db.query("SELECT action, status, desired_event FROM calendar_work_items WHERE event_id = ? "
                    "ORDER BY generation", (event_id,))
    return [db.schema.decode("calendar_work_items", r) for r in rows]


def _proposals(db, event_id: str) -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT status, kind, resolution_reason FROM event_change_proposals WHERE event_id = ? "
        "ORDER BY created_at, id", (event_id,))]


# --- the lease fence ------------------------------------------------------------


# Validates: SEL-165
def test_stale_generation_cannot_write(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user, worker="new-worker", generation=2)
    result = _commit(db, email, [_create(email, "must not exist")], worker="old-worker", generation=1)
    assert result == {"fenced": True, "applied": 0}
    assert _count(db, "SELECT count(*) FROM events WHERE title = 'must not exist'") == 0
    assert factory.row("emails", email)["processing_status"] == "processing"


def test_same_worker_with_an_old_generation_is_fenced(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user, worker="w", generation=3)
    assert _commit(db, email, [], worker="w", generation=2)["fenced"] is True


# Validates: SEL-165
def test_zombie_generation_after_reclaim_writes_nothing(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user, worker="replacement", generation=2)
    result = _commit(db, email, [], worker="zombie", generation=1)
    assert result["fenced"] is True
    assert factory.row("emails", email)["processing_status"] == "processing"
    assert factory.row("emails", email)["locked_by"] == "replacement"


def test_unknown_email_is_not_found(db, factory):
    with pytest.raises(errors.NotFound, match="not found"):
        _commit(db, "00000000-0000-4000-8000-000000000001", [])


def test_invalid_terminal_status_is_refused(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    with pytest.raises(errors.InvalidArgument, match="invalid extraction terminal status"):
        _commit(db, email, [], terminal="pending")


# Validates: SEL-169
def test_empty_commit_marks_the_email_terminal_and_releases_the_lease(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    assert _commit(db, email, [], terminal="skipped") == {
        "fenced": False, "conflict": False, "applied": 0, "event_ids": []}
    row = factory.row("emails", email)
    assert (row["processing_status"], row["locked_by"], row["locked_until"]) == ("skipped", None, None)
    assert row["processed_at"] is None, "processed_at is stamped only for 'processed'"
    _commit_processed = _claimed_email(factory, user, worker="w2")
    _commit(db, _commit_processed, [], worker="w2")
    assert factory.row("emails", _commit_processed)["processed_at"] is not None


# --- atomicity ------------------------------------------------------------------


# Validates: SEL-169
def test_multi_event_email_commits_all_or_nothing(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    decisions = [_create(email, "atomic"), {"action": "invalid", "event_id": None, "fields": {}, "source": {}}]
    with pytest.raises(errors.InvalidArgument, match="invalid extraction decision envelope"):
        _commit(db, email, decisions)
    assert _count(db, "SELECT count(*) FROM events WHERE title = 'atomic'") == 0
    assert factory.row("emails", email)["processing_status"] == "processing"


# Validates: SEL-169
def test_a_failure_late_in_the_write_loop_rolls_back_earlier_decisions(db, factory):
    """The second decision fails after the first has been inserted: nothing survives."""
    user = factory.user()
    email = _claimed_email(factory, user)
    bad = _create(email, "second", day="2026-09-15")
    bad["hints"] = [{"kind": "nonsense", "value_hash": "x", "strength": "supporting"}]
    with pytest.raises(errors.InvalidArgument, match="invalid identity hint"):
        _commit(db, email, [_create(email, "first"), bad])
    assert _count(db, "SELECT count(*) FROM events") == 0
    assert _count(db, "SELECT count(*) FROM event_sources") == 0
    assert factory.row("emails", email)["processing_status"] == "processing"


def test_noop_decisions_are_skipped_and_do_not_count(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    result = _commit(db, email, [{"action": "noop"}, _create(email, "real")])
    assert result["applied"] == 1 and len(result["event_ids"]) == 1


# --- the band fence -------------------------------------------------------------


# Validates: SEL-166
def test_stale_fingerprint_returns_conflict_and_mutates_nothing(db, factory):
    user = factory.user()
    winner = _claimed_email(factory, user, worker="winner")
    loser = _claimed_email(factory, user, worker="loser")
    assert _commit(db, winner, [_create(winner, "winner")], worker="winner")["applied"] == 1
    result = _commit(db, loser, [_create(loser, "loser")], worker="loser")
    assert result == {"fenced": False, "conflict": True, "conflicting_indexes": [0]}
    assert _count(db, "SELECT count(*) FROM events WHERE title = 'loser'") == 0
    assert factory.row("emails", loser)["processing_status"] == "processing", "a conflict is retried"


def test_a_band_changed_after_the_decision_is_refused(db, factory):
    """The race the fence exists for: the band moves between reading and committing."""
    user = factory.user()
    event = _active_event(factory, user, review_status="pending_review")
    email = _claimed_email(factory, user)
    decision = _update(db, user, email, event, intent="no_change",
                       fields={"description": "from the LLM", "review_status": "pending_review"})
    # Meanwhile another writer touches an event in the band.
    assert db_events.retire_pending(db, user, event) is True
    result = _commit(db, email, [decision])
    assert result["conflict"] is True
    assert db_events.get(db, user, event)["description"] is None


# Validates: SEL-166
def test_conflict_names_the_index_of_the_stale_decision(db, factory):
    user = factory.user()
    factory.event(user, start_datetime="2026-09-15T10:00:00.000000Z")
    email = _claimed_email(factory, user)
    result = _commit(db, email, [_create(email, "fine"), _create(email, "stale", day="2026-09-15")])
    assert result["conflicting_indexes"] == [1]
    assert _count(db, "SELECT count(*) FROM events WHERE title = 'fine'") == 0


def test_conflict_recomputed_fingerprint_matches_winner(db, factory):
    user = factory.user()
    winner = _claimed_email(factory, user, worker="winner")
    loser = _claimed_email(factory, user, worker="loser")
    event_id = _commit(db, winner, [_create(winner, "winner")], worker="winner")["event_ids"][0]
    row = db.query_one("SELECT id, updated_at FROM events WHERE id = ?", (event_id,))
    window = _window()
    result = _commit(db, loser, [{
        "action": "update", "event_id": event_id, "intent": "no_change",
        "window_start": window[0], "window_end": window[1],
        "expected_fingerprint": candidate_fingerprint([dict(row)]),
        "fields": {"description": "winner plus loser", "review_status": "pending_review"},
        "source": {"email_id": loser, "source_type": "update", "extracted_data": {}},
    }], worker="loser")
    assert result["conflict"] is False and result["applied"] == 1
    assert db_events.get(db, user, event_id)["description"] == "winner plus loser"
    assert _count(db, "SELECT count(*) FROM event_sources WHERE event_id = ?", (event_id,)) == 2


def test_two_emails_different_days_never_conflict(db, factory):
    user = factory.user()
    a = _claimed_email(factory, user, worker="a")
    b = _claimed_email(factory, user, worker="b")
    assert _commit(db, a, [_create(a, "a", day="2031-03-03")], worker="a")["applied"] == 1
    assert _commit(db, b, [_create(b, "b", day="2031-03-04")], worker="b")["applied"] == 1


# Validates: SEL-167
def test_producer_and_commit_fingerprints_agree(db, factory):
    """One implementation both sides: the producer's value is what the commit accepts."""
    user = factory.user()
    factory.event(user, start_datetime="2031-05-03T10:00:00.000000Z")
    factory.event(user, start_datetime="2031-05-03T23:59:59.999999Z")
    factory.event(user, start_datetime="2031-05-04T00:00:00.000000Z")  # outside: end is exclusive
    window = _window("2031-05-03")
    rows = db_events.in_window(db, user, *window)
    assert len(rows) == 2
    produced = db_events.band_fingerprint(db, user, *window)
    assert produced == candidate_fingerprint(rows)
    email = _claimed_email(factory, user)
    assert _commit(db, email, [_create(email, "third", day="2031-05-03", fingerprint=produced)])["applied"] == 1


def test_window_bounds_with_offsets_are_compared_as_instants(db, factory):
    user = factory.user()
    factory.event(user, start_datetime="2031-05-03T08:00:00.000000Z")
    # The same local day in UTC-7 ends at 07:00Z the next day; 08:00Z on the 3rd is inside.
    fp = db_events.band_fingerprint(db, user, "2031-05-03T00:00:00-07:00", "2031-05-04T00:00:00-07:00")
    assert fp != EMPTY
    assert db_events.band_fingerprint(db, user, "2031-05-03T00:00:00+00:00", "2031-05-03T08:00:00") == EMPTY


def test_another_users_events_are_outside_the_band(db, factory):
    user, other = factory.user(), factory.user()
    factory.event(other, start_datetime=f"{DAY}T10:00:00.000000Z")
    email = _claimed_email(factory, user)
    assert _commit(db, email, [_create(email, "mine")])["applied"] == 1


# --- the four intents -----------------------------------------------------------


def test_review_intent_holds_the_change_and_writes_no_calendar_work(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    event = _active_event(factory, user)
    result = _commit(db, email, [_update(db, user, email, event, intent="review",
                                         fields={"review_status": "active"},
                                         source=_change_source(email))])
    assert result["applied"] == 1
    assert [p["status"] for p in _proposals(db, event)] == ["pending"]
    row = db_events.get(db, user, event)
    assert (row["review_status"], row["location"]) == ("active", "Room A")
    assert _work(db, event) == []


def test_apply_intent_applies_the_change_and_queues_calendar_work(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    event = _active_event(factory, user)
    _commit(db, email, [_update(db, user, email, event, intent="apply", fields={
        "review_status": "active", "calendar_action": "upsert", "title": "Standup",
        "start_datetime": f"{DAY}T10:00:00Z", "end_datetime": f"{DAY}T11:00:00Z", "location": "Room B",
    }, source=_change_source(email))])
    proposals = _proposals(db, event)
    assert [(p["status"], p["resolution_reason"]) for p in proposals] == [("applied", "automatic_apply")]
    assert db_events.get(db, user, event)["location"] == "Room B"
    work = _work(db, event)
    assert [w["action"] for w in work] == ["upsert"]
    assert work[0]["desired_event"] == {
        "title": "Standup", "start_datetime": f"{DAY}T10:00:00Z", "end_datetime": f"{DAY}T11:00:00Z",
        "all_day": False, "location": "Room B", "description": None, "importance": "action_required",
    }


# Validates: SEL-176
def test_apply_intent_with_cancel_queues_a_cancellation_without_payload(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    event = _active_event(factory, user)
    source = {**_change_source(email), "source_type": "cancellation"}
    _commit(db, email, [_update(db, user, email, event, intent="apply",
                                fields={"review_status": "active", "calendar_action": "cancel"},
                                source=source)])
    assert [(p["status"], p["kind"]) for p in _proposals(db, event)] == [("applied", "cancellation")]
    assert [(w["action"], w["desired_event"]) for w in _work(db, event)] == [("cancel", None)]


def test_apply_intent_on_a_new_lane_event_queues_no_calendar_work(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    event = _active_event(factory, user, review_status="pending_review")
    _commit(db, email, [_update(db, user, email, event, intent="apply",
                                fields={"review_status": "pending_review", "location": "Room B"},
                                source=_change_source(email))])
    row = db_events.get(db, user, event)
    assert (row["review_status"], row["location"]) == ("pending_review", "Room B")
    assert _work(db, event) == []


# Validates: SEL-175
def test_update_applies_only_the_fields_present(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    event = _active_event(factory, user, review_status="pending_review", description="keep me")
    _commit(db, email, [_update(db, user, email, event, intent="no_change",
                                fields={"review_status": "pending_review", "location": None,
                                        "all_day": "t"})])
    row = db_events.get(db, user, event)
    assert row["location"] is None, "a present key with JSON null clears the column"
    assert row["description"] == "keep me", "an absent key leaves the column"
    assert row["all_day"] is True, "'t' is a Postgres boolean"
    assert row["title"] == "Standup"


# Validates: SEL-230
@pytest.mark.parametrize("declined", ["rejected", "cancelled"])
def test_record_only_leaves_a_declined_event_untouched(db, factory, declined):
    user = factory.user()
    email = _claimed_email(factory, user)
    event = _active_event(factory, user, review_status=declined)
    before = db_events.get(db, user, event)["updated_at"]
    _commit(db, email, [_update(db, user, email, event, intent="record_only", fields={},
                                source={"email_id": email, "extracted_data": {}, "source_type": "update"},
                                hints=[{"kind": "join_url", "value_hash": "c" * 64, "strength": "supporting"}])])
    row = db_events.get(db, user, event)
    assert (row["review_status"], row["location"], row["updated_at"]) == (declined, "Room A", before)
    assert _proposals(db, event) == [] and _work(db, event) == []
    assert _count(db, "SELECT count(*) FROM event_sources WHERE event_id = ? AND email_id = ?", (event, email)) == 1
    assert _count(db, "SELECT count(*) FROM event_identity_hints WHERE event_id = ?", (event,)) == 1


# Validates: SEL-177
def test_record_only_requires_an_update_decision(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    decision = {**_create(email, "x"), "intent": "record_only"}
    with pytest.raises(errors.InvalidArgument, match="record_only requires an update"):
        _commit(db, email, [decision])


# Validates: SEL-177
def test_an_update_of_another_users_event_is_refused(db, factory):
    user, other = factory.user(), factory.user()
    email = _claimed_email(factory, user)
    theirs = factory.event(other, start_datetime="2031-01-01T10:00:00.000000Z")
    decision = _update(db, user, email, theirs, intent="no_change", fields={"review_status": "active"})
    with pytest.raises(errors.NotOwned, match="is not owned by email user"):
        _commit(db, email, [decision])
    missing = {**decision, "event_id": None}
    with pytest.raises(errors.InvalidArgument, match="requires event_id"):
        _commit(db, email, [missing])


# --- fail-closed ----------------------------------------------------------------


# Validates: SEL-172
def test_a_decision_without_an_intent_is_refused(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    event = _active_event(factory, user)
    with pytest.raises(errors.InvalidArgument, match=r"known intent \(got <missing>\)"):
        _commit(db, email, [_update(db, user, email, event, fields={}, source=_change_source(email))])
    assert _proposals(db, event) == []


# Validates: SEL-173
def test_a_decision_without_a_review_status_is_refused(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    event = _active_event(factory, user)
    with pytest.raises(errors.InvalidArgument, match="explicit review_status"):
        _commit(db, email, [_update(db, user, email, event, intent="no_change", fields={})])


def test_review_intent_requires_an_active_event(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    event = _active_event(factory, user)
    with pytest.raises(errors.InvalidArgument, match="requires review_status active"):
        _commit(db, email, [_update(db, user, email, event, intent="review",
                                    fields={"review_status": "pending_review"}, source=_change_source(email))])


# Validates: SEL-174
def test_no_change_intent_cannot_carry_a_change_set(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    event = _active_event(factory, user)
    with pytest.raises(errors.InvalidArgument, match="cannot carry a change_set"):
        _commit(db, email, [_update(db, user, email, event, intent="no_change",
                                    fields={"review_status": "active"}, source=_change_source(email))])


# Validates: SEL-174
def test_apply_without_a_change_set_is_refused(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    event = _active_event(factory, user)
    with pytest.raises(errors.InvalidArgument, match="intent apply requires a change_set and snapshot"):
        _commit(db, email, [_update(db, user, email, event, intent="apply", fields={"review_status": "active"},
                                    source={"email_id": email, "extracted_data": {},
                                            "change_set": _change_set(), "event_snapshot_before": {}})])


# Validates: SEL-173
@pytest.mark.parametrize("fields, message", [
    ({"review_status": "approved"}, "invalid extraction review status approved"),
    ({"review_status": "active", "calendar_action": "delete"}, "invalid extraction calendar action delete"),
])
def test_unknown_states_are_refused(db, factory, fields, message):
    user = factory.user()
    email = _claimed_email(factory, user)
    event = _active_event(factory, user)
    with pytest.raises(errors.InvalidArgument, match=message):
        _commit(db, email, [_update(db, user, email, event, intent="no_change", fields=fields)])


# Validates: SEL-175
def test_creating_an_active_event_queues_its_calendar_write(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    event_id = _commit(db, email, [_create(email, "approved", review_status="active")])["event_ids"][0]
    assert [w["action"] for w in _work(db, event_id)] == ["upsert"]


# Validates: SEL-179
def test_create_defaults_and_naive_timestamps_are_utc(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    decision = _create(email, "naive")
    decision["fields"]["start_datetime"] = f"{DAY}T10:00:00"
    decision["fields"]["end_datetime"] = f"{DAY}T11:00:00+02:00"
    event_id = _commit(db, email, [decision])["event_ids"][0]
    row = db_events.get(db, user, event_id)
    assert row["start_datetime"] == f"{DAY}T10:00:00.000000Z"
    assert row["end_datetime"] == f"{DAY}T09:00:00.000000Z"
    assert (row["all_day"], row["importance"], row["review_status"]) == (False, "action_required", "pending_review")
    assert row["created_at"] == row["updated_at"]


def test_a_commit_announces_itself_after_commit_only(db, factory, monkeypatch):
    user = factory.user()
    email = _claimed_email(factory, user)
    published: list[tuple] = []
    monkeypatch.setattr(db.bus, "publish", lambda topic, msg: published.append((topic, msg["resource"])))
    with pytest.raises(errors.InvalidArgument):
        _commit(db, email, [_create(email, "x"), {"action": "bogus"}])
    assert published == []
    _commit(db, email, [_create(email, "x")])
    assert {r for _, r in published} >= {"events", "event_sources", "emails"}
    assert {t for t, _ in published} == {f"user:{user}"}


# --- sources --------------------------------------------------------------------


# Validates: SEL-178
def test_recommitting_an_email_upserts_its_source(db, factory):
    user = factory.user()
    event = _active_event(factory, user, review_status="pending_review")
    email = _claimed_email(factory, user)
    factory.event_source(event, email, source_type="new_invitation")
    _commit(db, email, [_update(db, user, email, event, intent="no_change",
                                fields={"review_status": "pending_review"},
                                source={"email_id": email, "source_type": "update",
                                        "extracted_data": {"again": True}})])
    rows = db_events.sources_with_emails(db, event)
    assert [(r["source_type"], r["extracted_data"]) for r in rows] == [("update", {"again": True})]
    assert rows[0]["emails"]["id"] == email


# Validates: SEL-178
def test_google_calendar_sources_and_extra_sources(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    decision = _create(email, "adopted")
    decision["source"] = {"source_origin": "google_calendar", "google_calendar_source_event_id": "g-1",
                          "source_type": "unknown", "extracted_data": {},
                          "extra_sources": [
                              {"source_origin": "google_calendar", "google_calendar_source_event_id": "g-2"},
                              {"source_origin": "email", "email_id": email},  # only calendar extras are written
                          ]}
    event_id = _commit(db, email, [decision])["event_ids"][0]
    assert sorted((s["source_origin"], s["source_type"]) for s in db_events.sources(db, event_id)) == [
        ("google_calendar", "unknown"), ("google_calendar", "unknown")]
    assert db_events.has_source_origin(db, event_id, "google_calendar")
    assert not db_events.has_source_origin(db, event_id, "email")


# --- identity hints -------------------------------------------------------------


# Validates: SEL-143
def test_commit_writes_identity_hints_in_same_transaction(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user, thread_id="thread-c2")
    value_hash = "a" * 64
    decision = _create(email, "C2 identity event", day="2035-01-02")
    decision.update(hint_keys=[f"ical_uid|{value_hash}|"], expected_hint_fingerprint=EMPTY, hints=[{
        "kind": "ical_uid", "value_hash": value_hash, "recurrence_id": "", "strength": "authoritative",
        "sequence": 1, "dtstamp": "2035-01-01T12:00:00Z"}])
    event_id = _commit(db, email, [decision])["event_ids"][0]
    hint = dict(db.query_one("SELECT * FROM event_identity_hints WHERE event_id = ?", (event_id,)))
    assert (hint["kind"], hint["value_hash"], hint["sequence"], hint["source_email_id"]) == (
        "ical_uid", value_hash, 1, email)
    assert hint["dtstamp"] == "2035-01-01T12:00:00.000000Z"
    assert hint["recurrence_id"] == ""
    keyed = db_events.hints_matching(db, user, [("ical_uid", value_hash, "")])
    assert [h["event_id"] for h in keyed[f"ical_uid|{value_hash}|"]] == [event_id]


# Validates: SEL-166
def test_hint_lookup_is_part_of_the_commit_fence(db, factory):
    user = factory.user()
    existing_email = factory.email(user, processing_status="processed")
    existing = factory.event(user, title="outside local day", start_datetime="2036-02-02T10:00:00.000000Z")
    value_hash = "b" * 64
    factory._insert("event_identity_hints", {
        "id": new_id(),
        "user_id": user, "event_id": existing, "source_email_id": existing_email,
        "kind": "join_url", "value_hash": value_hash, "strength": "supporting"})
    email = _claimed_email(factory, user)
    decision = _create(email, "must be fenced", day="2036-02-03")
    decision.update(hint_keys=[f"join_url|{value_hash}|"], expected_hint_fingerprint=EMPTY,
                    hints=[{"kind": "join_url", "value_hash": value_hash, "strength": "supporting"}])
    assert _commit(db, email, [decision])["conflict"] is True
    assert _count(db, "SELECT count(*) FROM events WHERE title = 'must be fenced'") == 0
    # Computed by the producer, the same decision commits.
    decision["expected_hint_fingerprint"] = db_events.hint_fingerprint(db, user, decision["hint_keys"])
    assert _commit(db, email, [decision])["applied"] == 1


def _calendar_entry(factory, user: str, **extra) -> str:
    integration = factory.integration(user, provider="google_calendar")
    return factory._insert("calendar_entries", {
        "id": new_id(), "user_id": user, "integration_id": integration, "calendar_id": "primary",
        "provider_event_id": f"probe-{new_id()[:8]}", "title": "Mirrored probe",
        "start_at": "2026-10-01T10:00:00.000000Z", **extra})


# Validates: SEL-166
def test_a_calendar_entry_hint_participates_in_the_fingerprint(db, factory):
    """A mirror sync that moves the matched entry between decision and commit is caught."""
    user = factory.user()
    entry = _calendar_entry(factory, user)
    value_hash = new_id().replace("-", "")
    factory._insert("event_identity_hints", {
        "id": new_id(), "user_id": user, "event_id": None, "calendar_entry_id": entry,
        "kind": "ical_uid", "value_hash": value_hash, "recurrence_id": "", "strength": "authoritative"})
    keys = [f"ical_uid|{value_hash}|"]
    produced = db_events.hint_fingerprint(db, user, keys)
    assert produced != EMPTY, "the entry is part of the hint read set"

    email = _claimed_email(factory, user)
    decision = _create(email, "fenced by the mirror", day="2026-10-01")
    decision.update(hint_keys=keys, expected_hint_fingerprint=produced)
    with db.write() as tx:  # the mirror updates the entry
        tx.execute("UPDATE calendar_entries SET title = 'moved', updated_at = ? WHERE id = ?", (tx.now_text, entry))
    assert db_events.hint_fingerprint(db, user, keys) != produced
    assert _commit(db, email, [decision])["conflict"] is True
    decision["expected_hint_fingerprint"] = db_events.hint_fingerprint(db, user, keys)
    assert _commit(db, email, [decision])["applied"] == 1


# Validates: SEL-144
def test_a_hint_must_name_exactly_one_entity(db, factory):
    user = factory.user()
    entry = _calendar_entry(factory, user)
    event = factory.event(user)
    for event_id, entry_id in ((event, entry), (None, None)):
        with pytest.raises(errors.CheckViolation, match="one_entity"):
            factory._insert("event_identity_hints", {
                "id": new_id(), "user_id": user, "event_id": event_id, "calendar_entry_id": entry_id,
                "kind": "ical_uid", "value_hash": new_id(), "recurrence_id": "", "strength": "authoritative"})


# Validates: SEL-143
def test_hint_upsert_is_idempotent_and_ical_sequence_only_moves_forward(db, factory):
    user = factory.user()
    event = _active_event(factory, user, review_status="pending_review")

    def commit(sequence, dtstamp, strength="authoritative", kind="ical_uid"):
        email = _claimed_email(factory, user, worker=f"w{sequence}{kind}")
        _commit(db, email, [_update(db, user, email, event, intent="no_change",
                                    fields={"review_status": "pending_review"},
                                    hints=[{"kind": kind, "value_hash": "d" * 64, "strength": strength,
                                            "sequence": sequence, "dtstamp": dtstamp}])],
                worker=f"w{sequence}{kind}")
        return email

    commit(3, "2026-01-03T00:00:00Z")
    latest = commit(1, "2026-01-01T00:00:00Z", strength="supporting")
    rows = [dict(r) for r in db.query("SELECT * FROM event_identity_hints WHERE event_id = ?", (event,))]
    assert len(rows) == 1
    assert (rows[0]["sequence"], rows[0]["dtstamp"]) == (3, "2026-01-03T00:00:00.000000Z")
    assert (rows[0]["strength"], rows[0]["source_email_id"]) == ("supporting", latest)
    commit(5, "")
    row = dict(db.query_one("SELECT sequence, dtstamp FROM event_identity_hints WHERE event_id = ?", (event,)))
    assert row == {"sequence": 5, "dtstamp": None}
    # Non-UID kinds never move sequence (it stays at the first insert's value).
    commit(7, None, kind="join_url")
    commit(9, None, kind="join_url")
    seq = db.query_one("SELECT sequence FROM event_identity_hints WHERE event_id = ? AND kind = 'join_url'", (event,))
    assert seq[0] == 7


def test_distinct_event_hints_coexist(db, factory):
    user = factory.user()
    email = _claimed_email(factory, user)
    decision = _create(email, "two hints")
    decision["hints"] = [{"kind": "join_url", "value_hash": "e" * 64, "strength": "supporting"},
                         {"kind": "join_url", "value_hash": "f" * 64, "strength": "supporting"}]
    event_id = _commit(db, email, [decision])["event_ids"][0]
    assert _count(db, "SELECT count(*) FROM event_identity_hints WHERE event_id = ?", (event_id,)) == 2


# Validates: SEL-143
@pytest.mark.parametrize("hint", [
    {"kind": "uid", "value_hash": "x", "strength": "supporting"},
    {"kind": "join_url", "value_hash": "x", "strength": "strong"},
    {"kind": "join_url", "value_hash": "", "strength": "supporting"},
    {"kind": "join_url", "strength": "supporting"},
])
def test_invalid_identity_hints_are_refused(db, factory, hint):
    user = factory.user()
    email = _claimed_email(factory, user)
    decision = _create(email, "hinted")
    decision["hints"] = [hint]
    with pytest.raises(errors.InvalidArgument, match="invalid identity hint"):
        _commit(db, email, [decision])


# --- set_event_review_status ----------------------------------------------------


# Validates: SEL-206, SEL-207
def test_approve_enqueues_upsert_and_reject_does_not(db, factory):
    user = factory.user()
    approved = factory.event(user, title="approve me", location="Here")
    rejected = factory.event(user, title="reject me")
    result = db_events.set_event_review_status(db, user, approved, "active")
    assert result["review_status"] == "active" and result["generation"] == 1
    work = _work(db, approved)
    assert [w["action"] for w in work] == ["upsert"]
    assert work[0]["desired_event"]["title"] == "approve me"
    assert work[0]["desired_event"]["location"] == "Here"
    assert "source_attribution" in work[0]["desired_event"]
    assert db_events.get(db, user, approved)["review_status"] == "active"

    result = db_events.set_event_review_status(db, user, rejected, "rejected")
    assert result == {"event_id": rejected, "review_status": "rejected", "work_item_id": None, "generation": None}
    assert _work(db, rejected) == []
    assert db_events.get(db, user, rejected)["review_status"] == "rejected"


# Validates: SEL-209
def test_approving_a_rejected_event_revives_it_explicitly(db, factory):
    user = factory.user()
    event = factory.event(user, review_status="rejected")
    db_events.set_event_review_status(db, user, event, "active")
    assert db_events.get(db, user, event)["review_status"] == "active"
    assert [w["action"] for w in _work(db, event)] == ["upsert"]


# Validates: SEL-208
def test_review_status_is_owner_only_and_validated(db, factory):
    user, other = factory.user(), factory.user()
    event = factory.event(user)
    with pytest.raises(errors.NotOwned, match="not owned by the caller"):
        db_events.set_event_review_status(db, other, event, "active")
    with pytest.raises(errors.NotOwned, match="authentication required"):
        db_events.set_event_review_status(db, None, event, "active")
    with pytest.raises(errors.InvalidArgument, match="invalid event review status"):
        db_events.set_event_review_status(db, user, event, "cancelled")
    assert db_events.get(db, user, event)["review_status"] == "pending_review"


# --- reads ----------------------------------------------------------------------


def test_reads_are_scoped_to_the_owner(db, factory):
    user, other = factory.user(), factory.user()
    event = factory.event(user)
    assert db_events.get(db, user, event)["id"] == event
    assert db_events.get(db, other, event) is None
    assert db_events.get_with_work_items(db, other, event) is None
    assert [e["id"] for e in db_events.get_many(db, user, [event])] == [event]
    assert db_events.get_many(db, other, [event]) == []
    email = factory.email(user)
    factory.event_source(event, email)
    assert db_events.event_ids_for_email(db, user, email) == [event]
    assert db_events.event_ids_for_email(db, other, email) == []


def test_get_with_work_items_embeds_the_items(db, factory):
    user = factory.user()
    event = factory.event(user)
    db_events.set_event_review_status(db, user, event, "active")
    db_events.set_event_review_status(db, user, event, "active")
    row = db_events.get_with_work_items(db, user, event)
    assert [(i["generation"], i["status"]) for i in row["calendar_work_items"]] == [(1, "superseded"), (2, "pending")]
    assert set(row["calendar_work_items"][0]) == {"status", "action", "generation", "failure_code"}


# Validates: SEL-156
def test_by_provider_event_id_returns_the_oldest_even_when_declined(db, factory):
    user = factory.user()
    first = factory.event(user, review_status="rejected", google_calendar_event_id="g-1",
                          created_at="2026-01-01T00:00:00.000000Z")
    factory.event(user, google_calendar_event_id="g-1", created_at="2026-02-01T00:00:00.000000Z")
    assert db_events.by_provider_event_id(db, user, "g-1")["id"] == first
    assert db_events.by_provider_event_id(db, user, "g-2") is None


def test_source_reads(db, factory):
    user = factory.user()
    event = factory.event(user)
    first = factory.email(user, date_sent="2026-01-01T00:00:00.000000Z")
    second = factory.email(user, date_sent="2026-03-01T00:00:00.000000Z")
    factory.event_source(event, first, source_type="new_invitation")
    factory.event_source(event, second, source_type="cancellation")
    factory.event_source(event)  # a calendar source with no email
    assert sorted(d for d in db_events.source_email_dates(db, event) if d) == [
        "2026-01-01T00:00:00.000000Z", "2026-03-01T00:00:00.000000Z"]
    assert None in db_events.source_email_dates(db, event)
    assert sorted(db_events.source_email_ids(db, event)) == sorted([first, second])
    assert db_events.source_types_for_email(db, second) == ["cancellation"]
    with_emails = db_events.sources_with_emails(db, event)
    assert len(with_emails) == 3
    assert sum(s["emails"] is None for s in with_emails) == 1


# --- the late calendar match (test_integration_late_calendar_match.py) -----------


def test_retire_pending_is_a_compare_and_set(db, factory):
    user = factory.user()
    pending = factory.event(user, title="Supercuts Appointment", start_datetime="2026-11-01T17:40:00.000000Z")
    found = db_events.pending_in_window(db, user, "2026-11-01T17:40:00+00:00", "2026-11-01T17:40:00+00:00")
    assert [e["id"] for e in found] == [pending], "both bounds are inclusive"
    assert set(found[0]) == {"id", "title", "start_datetime", "end_datetime", "location", "description"}
    assert db_events.retire_pending(db, user, pending) is True
    assert db_events.get(db, user, pending)["review_status"] == "rejected"
    assert db_events.retire_pending(db, user, pending) is False


def test_an_approved_event_is_not_retired(db, factory):
    user = factory.user()
    approved = factory.event(user, review_status="active", start_datetime="2026-11-01T17:40:00.000000Z")
    assert db_events.pending_in_window(db, user, "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z") == []
    assert db_events.retire_pending(db, user, approved) is False
    assert db_events.get(db, user, approved)["review_status"] == "active"


# --- the decisions the service actually builds, through the real commit ------------


def test_a_booking_reopens_a_rejected_event_into_the_new_lane(db, factory):
    from selko.api.schemas.calendar import CalendarEvent, CalendarEventExtraction
    from selko.services.events import EventMatch, save_extracted_events

    user = factory.user()
    email = _claimed_email(factory, user)
    event = _active_event(factory, user, review_status="rejected")
    extraction = CalendarEventExtraction(
        email_message_id="receipt", sender_email="tickets@example.com", events_found=True,
        booking_confirmed=True,
        events=[CalendarEvent(title="Standup", start_datetime=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
                              description="tickets")],
    )
    captured: list[dict] = []

    def capture(client, email_id, locked_by, lock_generation, decisions, terminal="processed"):
        captured.extend(decisions)
        return {"fenced": False, "applied": len(decisions), "event_ids": []}

    match = EventMatch(match_id=event, baseline={**_snapshot(), "review_status": "rejected"})
    with patch("selko.services.events.find_matching_event", return_value=match), \
         patch("selko.services.events._commit_email_extraction", side_effect=capture), \
         patch("selko.services.events._load_identity_context", return_value=({}, [])), \
         patch("selko.services.events.calendars.get_all_day_policy_and_timezone",
               return_value=(MagicMock(mode="all_day"), "UTC")):
        save_extracted_events(db, MagicMock(), user, email, extraction)

    assert len(captured) == 1
    window = _update(db, user, email, event)
    _commit(db, email, [{**captured[0], **{k: window[k] for k in ("window_start", "window_end", "expected_fingerprint")},
                         "source": {**captured[0]["source"], "email_id": email}}])
    row = db_events.get(db, user, event)
    assert (row["review_status"], row["location"]) == ("pending_review", "Room A")
    assert _work(db, event) == []
    assert [(p["status"], p["kind"]) for p in _proposals(db, event)] == [("applied", "material_update")]


# Validates: SEL-222, SEL-223
@pytest.mark.parametrize("adopted_from_calendar", [False, True])
def test_an_update_applies_to_a_selko_event_and_waits_on_a_calendar_one(db, factory, adopted_from_calendar):
    from selko.api.schemas.calendar import CalendarEvent, CalendarEventExtraction
    from selko.services.event_diff import EventChangeSet, FieldChange
    from selko.services.events import EventMatch, save_extracted_events

    user = factory.user()
    email = _claimed_email(factory, user)
    event = _active_event(factory, user)
    factory.event_source(event, email, source_type="new_invitation")
    if adopted_from_calendar:
        factory.event_source(event, source_type="unknown")
    extraction = CalendarEventExtraction(
        email_message_id="update", sender_email="organizer@example.com", events_found=True,
        events=[CalendarEvent(title="Standup", start_datetime=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
                              location="Room B", description="moved")],
    )
    captured: list[dict] = []

    def capture(client, email_id, locked_by, lock_generation, decisions, terminal="processed"):
        captured.extend(decisions)
        return {"fenced": False, "applied": len(decisions), "event_ids": []}

    change_set = EventChangeSet(kind="material_update", changes=[
        FieldChange(field="location", before="Room A", after="Room B", reason="moved")])
    with patch("selko.services.events.find_matching_event", return_value=EventMatch(match_id=event, baseline=_snapshot())), \
         patch("selko.services.events._commit_email_extraction", side_effect=capture), \
         patch("selko.services.events._is_from_users_calendar",
               side_effect=lambda _client, event_id: db_events.has_source_origin(db, event_id, "google_calendar")), \
         patch("selko.services.events._fetch_baseline_info_date",
               side_effect=lambda _client, event_id: max(
                   [d for d in db_events.source_email_dates(db, event_id) if d], default=None)), \
         patch("selko.services.events.event_processing.propose_event_update", return_value=change_set):
        save_extracted_events(db, MagicMock(), user, email, extraction)

    window = _update(db, user, email, event)
    _commit(db, email, [{**captured[0], **{k: window[k] for k in ("window_start", "window_end", "expected_fingerprint")}}])
    row = db_events.get(db, user, event)
    proposals = _proposals(db, event)
    work = _work(db, event)
    if adopted_from_calendar:
        assert row["location"] == "Room A"
        assert [p["status"] for p in proposals] == ["pending"]
        assert work == []
    else:
        assert row["location"] == "Room B"
        assert [p["status"] for p in proposals] == ["applied"]
        assert [(w["action"], w["desired_event"]["location"]) for w in work] == [("upsert", "Room B")]


# --- Postgres value semantics ---------------------------------------------------


@pytest.mark.parametrize("text, expected", [
    ("t", True), ("TRUE", True), (" yes ", True), ("on", True), ("1", True),
    ("f", False), ("False", False), ("no", False), ("off", False), ("of", False), ("0", False), (None, None),
])
def test_pg_bool(text, expected):
    assert db_events.pg_bool(text) is expected


@pytest.mark.parametrize("text", ["o", "maybe", "2"])
def test_pg_bool_refuses_what_postgres_refuses(text):
    with pytest.raises(errors.InvalidArgument):
        db_events.pg_bool(text)


def test_jtext_is_postgres_arrow_arrow():
    obj = {"s": "x", "n": 3, "b": True, "z": None, "o": {"a": 1}}
    assert [db_events.jtext(obj, k) for k in ("s", "n", "b", "z", "o", "missing")] == [
        "x", "3", "true", None, '{"a": 1}', None]
    assert db_events.jtext(["not", "an", "object"], "s") is None


def test_pg_like_is_case_sensitive_with_postgres_wildcards():
    assert db_events.pg_like("news@example.edu", "%@example.edu")
    assert not db_events.pg_like("news@EXAMPLE.edu", "%@example.edu")
    assert db_events.pg_like("news@exampleXedu", "%@example_edu")
    assert not db_events.pg_like("news@example.edu.evil", "%@example.edu")
    assert not db_events.pg_like(None, "%")
    assert json.loads(db_events.json_text(None)) is None
