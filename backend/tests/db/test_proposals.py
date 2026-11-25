"""`selko.db.proposals` against a real SQLite database.

Ports the assertions of integration/test_integration_event_change_proposals.py,
the proposal tests of integration/test_schema_contract.py
(``test_pending_proposal_requires_active_review_status``,
``test_reject_event_change_proposal_is_one_atomic_transition``) and the undo /
redo tests of integration/test_integration_events.py. No database call is
mocked; the deferred invariant is the one `Tx` checks before COMMIT.
"""

from __future__ import annotations

import pytest
from selko.db import errors, proposals
from selko.db import events as db_events
from selko.db.codec import new_id


def _snapshot(title: str = "before") -> dict:
    return {"title": title, "start_datetime": "2026-09-01T14:00:00Z", "end_datetime": "2026-09-01T15:00:00Z",
            "all_day": False, "location": None, "description": None, "importance": "action_required",
            "review_status": "active"}


def _change_set(before: str = "before", after: str = "after") -> dict:
    return {"kind": "material_update", "changes": [{"field": "title", "before": before, "after": after}]}


def _event(factory, user: str, title: str = "before", **extra) -> str:
    values = {"start_datetime": "2026-09-01T14:00:00.000000Z", "end_datetime": "2026-09-01T15:00:00.000000Z"}
    values.update(extra)
    return factory.event(user, review_status=values.pop("review_status", "active"), title=title, **values)


def _proposal(factory, user: str, event: str, status: str = "pending", snapshot: dict | None = None,
              change_set: dict | None = None, **extra) -> str:
    email = factory.email(user)
    source = factory.event_source(event, email, source_type="update")
    return factory._insert("event_change_proposals", {
        "id": new_id(), "event_id": event, "user_id": user, "source_id": source, "kind": "material_update",
        "status": status, "change_set": change_set or _change_set(), "event_snapshot_before": snapshot or _snapshot(),
        **extra})


def _apply(db, user, event, proposal, **overrides) -> dict:
    args = {"expected_hash": None, "title": "after", "start_datetime": "2026-09-01T14:00:00Z",
            "end_datetime": "2026-09-01T15:00:00Z", "all_day": False, "location": None, "description": None,
            "importance": "action_required", "review_status": "active", "calendar_sync_action": "upsert"}
    args.update(overrides)
    return proposals.apply_event_change_proposal(db, user, event, proposal, **args)


def _reject(db, user, event, proposal, **overrides) -> dict:
    args = {"expected_hash": None, "delete_event": False, "title": "before", "start_datetime": None,
            "end_datetime": None, "all_day": False, "location": None, "description": None,
            "importance": "action_required", "resolution_reason": "user_rejected"}
    args.update(overrides)
    return proposals.reject_event_change_proposal(db, user, event, proposal, **args)


def _status(factory, proposal: str) -> str:
    return factory.row("event_change_proposals", proposal)["status"]


def _work(db, event: str) -> list[dict]:
    return [db.schema.decode("calendar_work_items", r) for r in db.query(
        "SELECT * FROM calendar_work_items WHERE event_id = ? ORDER BY generation", (event,))]


# --- the deferred invariant -----------------------------------------------------


def test_pending_proposal_requires_active_review_status(db, factory):
    user = factory.user()
    event = _event(factory, user, review_status="pending_review")
    with pytest.raises(errors.InvariantViolation, match="must have active review status"):
        _proposal(factory, user, event, snapshot={"status": "approved", "title": "before"},
                  change_set={"kind": "material_update", "changes": []})
    assert db.query_one("SELECT count(*) FROM event_change_proposals")[0] == 0, "rolled back"


def test_the_invariant_is_checked_at_commit_not_per_statement(db, factory):
    """A transition may pass through an illegal state inside one transaction."""
    user = factory.user()
    event = _event(factory, user, review_status="pending_review")
    email = factory.email(user)
    source = factory.event_source(event, email, source_type="update")
    with db.write() as tx:
        tx.execute(
            "INSERT INTO event_change_proposals (id, event_id, user_id, source_id, kind, status, change_set, "
            "event_snapshot_before) VALUES (?, ?, ?, ?, 'material_update', 'pending', ?, ?)",
            (new_id(), event, user, source, '{"a":1}', '{"b":2}'),
        )
        tx.execute("UPDATE events SET review_status = 'active' WHERE id = ?", (event,))
    assert db.query_one("SELECT count(*) FROM event_change_proposals WHERE status = 'pending'")[0] == 1
    with pytest.raises(errors.InvariantViolation, match="must have active review status"), db.write() as tx:
        tx.execute("UPDATE events SET review_status = 'rejected' WHERE id = ?", (event,))
    assert db_events.get(db, user, event)["review_status"] == "active"


def test_one_pending_proposal_per_event(db, factory):
    user = factory.user()
    event = _event(factory, user)
    _proposal(factory, user, event)
    with pytest.raises(errors.UniqueViolation):
        _proposal(factory, user, event)


# --- apply / reject / reopen ----------------------------------------------------


def test_proposal_is_authoritative_and_apply_reject_reopen_are_atomic(db, factory):
    user = factory.user()
    event = _event(factory, user)
    proposal = _proposal(factory, user, event)
    applied = _apply(db, user, event, proposal)
    assert applied["proposal_id"] == proposal and applied["review_status"] == "active"
    row = factory.row("event_change_proposals", proposal)
    assert (row["status"], row["resolution_reason"]) == ("applied", "user_applied")
    assert row["resolved_at"] is not None
    work = _work(db, event)
    assert applied["calendar_work_id"] == work[0]["id"]
    assert work[0]["desired_event"]["title"] == "after"
    assert work[0]["desired_event"]["start_datetime"] == "2026-09-01T14:00:00.000000Z"
    assert db_events.get(db, user, event)["title"] == "after"

    reopened = proposals.reopen_event_change_proposal(db, user, event, proposal, None)
    assert reopened == {"event_id": event, "proposal_id": proposal, "status": "active", "calendar_work": None}
    assert _status(factory, proposal) == "pending"
    restored = db_events.get(db, user, event)
    assert (restored["review_status"], restored["title"]) == ("active", "before")
    row = factory.row("event_change_proposals", proposal)
    assert (row["resolution_reason"], row["resolved_at"]) == (None, None)


def test_apply_a_cancellation_without_a_provider_event_is_terminal(db, factory):
    user = factory.user()
    event = _event(factory, user)
    proposal = _proposal(factory, user, event)
    result = _apply(db, user, event, proposal, review_status="cancelled", calendar_sync_action="cancel")
    assert result["calendar_work_id"] is None
    assert db_events.get(db, user, event)["review_status"] == "cancelled"
    assert _work(db, event) == []


def test_apply_cancel_on_an_active_event_queues_a_cancellation(db, factory):
    user = factory.user()
    event = _event(factory, user, google_calendar_event_id="g-1")
    proposal = _proposal(factory, user, event)
    _apply(db, user, event, proposal, calendar_sync_action="cancel")
    work = _work(db, event)
    assert [(w["action"], w["desired_event"], w["provider_event_id"]) for w in work] == [("cancel", None, "g-1")]


def test_apply_validates_after_locking_and_rolls_back(db, factory):
    user = factory.user()
    event = _event(factory, user)
    proposal = _proposal(factory, user, event)
    with pytest.raises(errors.InvalidArgument, match="invalid proposal application state"):
        _apply(db, user, event, proposal, review_status="pending_review")
    with pytest.raises(errors.InvalidArgument, match="invalid proposal application state"):
        _apply(db, user, event, proposal, calendar_sync_action="delete")
    assert _status(factory, proposal) == "pending"
    assert db_events.get(db, user, event)["title"] == "before"


def test_transitions_refuse_what_is_not_owned_or_not_pending(db, factory):
    user, other = factory.user(), factory.user()
    event = _event(factory, user)
    proposal = _proposal(factory, user, event)
    with pytest.raises(errors.NotOwned, match="is not owned by user"):
        _apply(db, other, event, proposal)
    with pytest.raises(errors.NotOwned, match="is not owned by user"):
        _reject(db, other, event, proposal)
    with pytest.raises(errors.ProposalStateError, match="not an owned pending proposal"):
        _apply(db, user, event, new_id())
    _apply(db, user, event, proposal)
    with pytest.raises(errors.ProposalStateError, match="not an owned pending proposal"):
        _apply(db, user, event, proposal)
    with pytest.raises(errors.ProposalStateError, match="not an owned pending proposal"):
        _reject(db, user, event, proposal)


def test_reject_event_change_proposal_is_one_atomic_transition(db, factory):
    user = factory.user()
    event = _event(factory, user, title="after", location="Changed")
    proposal = _proposal(factory, user, event, snapshot={"status": "approved", "title": "before"},
                         change_set={"kind": "material_update", "changes": []})
    result = _reject(db, user, event, proposal)
    assert result == {"event_id": event, "proposal_id": proposal, "status": "active"}
    row = factory.row("event_change_proposals", proposal)
    assert (row["status"], row["resolution_reason"]) == ("rejected", "user_rejected")
    restored = db_events.get(db, user, event)
    assert (restored["review_status"], restored["title"], restored["location"], restored["start_datetime"]) == (
        "active", "before", None, None)


def test_reject_reason_is_validated(db, factory):
    user = factory.user()
    event = _event(factory, user)
    proposal = _proposal(factory, user, event)
    with pytest.raises(errors.InvalidArgument, match="invalid proposal rejection reason"):
        _reject(db, user, event, proposal, resolution_reason="because")
    assert _status(factory, proposal) == "pending"


def test_reject_deletes_an_unsynced_calendar_only_adopt(db, factory):
    user = factory.user()
    event = _event(factory, user, google_calendar_event_id="g-adopted")
    proposal = _proposal(factory, user, event)
    _proposal(factory, user, event, status="superseded")  # history on the same event goes with it
    assert _reject(db, user, event, proposal, delete_event=True)["status"] == "deleted"
    assert db_events.get(db, user, event) is None
    assert db.query_one("SELECT count(*) FROM event_change_proposals")[0] == 0
    assert db.query_one("SELECT count(*) FROM event_sources")[0] == 0


@pytest.mark.parametrize("extra", [{}, {"google_calendar_event_id": "g", "synced_at": "2026-01-01T00:00:00.000000Z"}])
def test_reject_delete_refuses_anything_but_a_calendar_only_adopt(db, factory, extra):
    user = factory.user()
    event = _event(factory, user, **extra)
    proposal = _proposal(factory, user, event)
    with pytest.raises(errors.InvalidArgument, match="not an unsynced calendar-only proposal"):
        _reject(db, user, event, proposal, delete_event=True)
    assert db_events.get(db, user, event) is not None


def test_undo_restores_snapshot(db, factory):
    """test_integration_events: undo of an applied update reopens it and restores the snapshot."""
    user = factory.user()
    event = _event(factory, user, title="Team Meeting - Updated", start_datetime="2026-03-20T15:00:00.000000Z",
                   end_datetime="2026-03-20T16:00:00.000000Z", location="Somewhere", all_day=True)
    proposal = _proposal(factory, user, event, status="applied", resolution_reason="approved", snapshot={
        "title": "Team Meeting", "start_datetime": "2026-03-20T14:00:00Z", "end_datetime": "",
        "review_status": "active"})
    proposals.reopen_event_change_proposal(db, user, event, proposal)
    row = db_events.get(db, user, event)
    assert row["title"] == "Team Meeting"
    assert row["start_datetime"] == "2026-03-20T14:00:00.000000Z"
    assert row["end_datetime"] is None, "an empty snapshot value is NULL"
    assert row["location"] is None, "an absent snapshot key clears the column"
    assert row["all_day"] is False
    assert row["importance"] == "action_required", "importance falls back to the current value"
    assert _status(factory, proposal) == "pending"


def test_redo_reapplies_a_reopened_proposal(db, factory):
    user = factory.user()
    event = _event(factory, user, title="Party")
    proposal = _proposal(factory, user, event, status="applied",
                         snapshot={"title": "Party", "review_status": "active"})
    proposals.reopen_event_change_proposal(db, user, event, proposal)
    assert _status(factory, proposal) == "pending"
    _apply(db, user, event, proposal, title="Party")
    assert _status(factory, proposal) == "applied"


def test_reopen_can_queue_compensating_calendar_work(db, factory):
    user = factory.user()
    event = _event(factory, user, google_calendar_event_id="g-1")
    proposal = _proposal(factory, user, event, status="applied")
    result = proposals.reopen_event_change_proposal(db, user, event, proposal, None, "upsert",
                                                    {"title": "before"}, "rev-1", True)
    item = result["calendar_work"]
    assert (item["action"], item["desired_event"], item["expected_provider_revision"], item["force_overwrite"]) == (
        "upsert", {"title": "before"}, "rev-1", True)
    assert item["provider_event_id"] == "g-1"


def test_reopen_refuses_a_proposal_that_is_not_applied(db, factory):
    user, other = factory.user(), factory.user()
    event = _event(factory, user)
    proposal = _proposal(factory, user, event)
    with pytest.raises(errors.ProposalStateError, match="is not an applied proposal"):
        proposals.reopen_event_change_proposal(db, user, event, proposal)
    with pytest.raises(errors.NotOwned, match="is not owned"):
        proposals.reopen_event_change_proposal(db, other, event, proposal)


# --- the hash fence -------------------------------------------------------------


def test_hash_round_trip_and_stale_hash(db, factory):
    user = factory.user()
    event = _event(factory, user)
    proposal = _proposal(factory, user, event)
    row = factory.row("event_change_proposals", proposal)
    digest = proposals.event_change_proposal_hash(row)
    assert digest == proposals.event_change_proposal_hash(dict(row))
    for key, value in (("status", "applied"), ("change_set", {"x": 1}), ("updated_at", "later")):
        assert proposals.event_change_proposal_hash({**row, key: value}) != digest
    with pytest.raises(errors.StaleProposal, match="changed before transition"):
        _apply(db, user, event, proposal, expected_hash="0" * 64)
    assert _status(factory, proposal) == "pending"
    _apply(db, user, event, proposal, expected_hash=digest)
    assert _status(factory, proposal) == "applied"
    applied = factory.row("event_change_proposals", proposal)
    with pytest.raises(errors.StaleProposal, match="changed before reopen"):
        proposals.reopen_event_change_proposal(db, user, event, proposal, digest)
    proposals.reopen_event_change_proposal(db, user, event, proposal,
                                           proposals.event_change_proposal_hash(applied))


def test_resolve_closes_a_legacy_proposal(db, factory):
    user = factory.user()
    event = _event(factory, user)
    legacy = _proposal(factory, user, event, status="closed_legacy")
    with pytest.raises(errors.InvalidArgument, match="invalid proposal resolution reason"):
        proposals.resolve_event_change_proposal(db, user, event, legacy, None, "user_rejected")
    assert proposals.resolve_event_change_proposal(db, user, event, legacy, None, "historical_proposal_cleanup") == {
        "event_id": event, "proposal_id": legacy, "status": "rejected"}
    with pytest.raises(errors.ProposalStateError, match="closed legacy"):
        proposals.resolve_event_change_proposal(db, user, event, legacy, None, "historical_proposal_cleanup")


# --- supersession through the real commit ---------------------------------------


def test_new_proposal_supersedes_only_the_previous_pending_proposal(db, factory):
    user = factory.user()
    event = _event(factory, user, title="one")
    history = _proposal(factory, user, event, status="rejected")

    def held_for_review(before, after):
        email = factory.email(user, processing_status="processing", locked_by="w",
                              locked_until="2099-01-01T00:00:00.000000Z", lock_generation=1)
        window = ("2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z")
        db_events.commit_email_extraction(db, email, "w", 1, [{
            "action": "update", "event_id": event, "intent": "review",
            "window_start": window[0], "window_end": window[1],
            "expected_fingerprint": db_events.band_fingerprint(db, user, *window),
            "fields": {"review_status": "active"},
            "source": {"email_id": email, "source_type": "update", "extracted_data": {},
                       "change_set": _change_set(before, after), "event_snapshot_before": _snapshot(before)},
        }], "processed")

    held_for_review("one", "two")
    held_for_review("two", "three")
    rows = [dict(r) for r in db.query(
        "SELECT id, status, resolution_reason, change_set FROM event_change_proposals WHERE event_id = ? "
        "ORDER BY created_at, id", (event,))]
    assert [r["status"] for r in rows] == ["rejected", "superseded", "pending"]
    assert rows[0]["id"] == history and rows[1]["resolution_reason"] == "superseded_by_newer_proposal"
    pending = proposals.get_pending(db, user, event)
    assert pending["change_set"]["changes"][0]["after"] == "three"
    assert proposals.get(db, user, event, pending["id"])["id"] == pending["id"]
    assert proposals.get_pending(db, factory.user(), event) is None


def test_latest_applied_sorts_null_resolution_first_like_postgres(db, factory):
    user = factory.user()
    event = _event(factory, user)
    older = _proposal(factory, user, event, status="applied", resolved_at="2026-01-01T00:00:00.000000Z")
    newer = _proposal(factory, user, event, status="applied", resolved_at="2026-02-01T00:00:00.000000Z")
    assert proposals.latest_applied(db, user, event)["id"] == newer
    unresolved = _proposal(factory, user, event, status="applied")
    assert proposals.latest_applied(db, user, event)["id"] == unresolved, "Postgres DESC puts NULLs first"
    assert older != newer
    assert proposals.latest_applied(db, factory.user(), event) is None


def test_deleting_an_account_with_a_proposal_cascades(db, factory):
    """A RESTRICT foreign key on the proposal's source once broke account deletion mid-cascade."""
    from selko.db import accounts as account_rows

    user = factory.user()
    event = factory.event(user, review_status="active")
    source = factory.event_source(event)
    with db.write() as tx:
        tx.execute(
            "INSERT INTO event_change_proposals (id, user_id, event_id, source_id, kind, status, change_set, event_snapshot_before)"
            " VALUES (?, ?, ?, ?, 'material_update', 'pending', '{\"title\":\"x\"}', '{\"title\":\"y\"}')",
            (new_id(), user, event, source),
        )
    assert account_rows.delete_account(db, user)
    assert db.query_one("SELECT count(*) FROM event_change_proposals")[0] == 0
