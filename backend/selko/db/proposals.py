"""Event change proposals: the Changes lane's transitions and reads.

Ports of ``_lock_owned_pending_proposal``, ``event_change_proposal_hash``,
``apply_event_change_proposal``, ``reject_event_change_proposal``,
``reopen_event_change_proposal`` and ``resolve_event_change_proposal``
(docs/specs/sqlite-single-process/02-data-layer.md §2.6). The deferred
invariant (``enforce_event_change_proposal_invariant``, §5.5) is checked by
`Tx` before COMMIT for every event a transaction touched, so a transition may
pass through an intermediate state (reopen sets the proposal pending before the
event active) exactly as it could in Postgres.

Each transition has a ``*_in_tx`` form so another function can run it inside
its own transaction (``sender_rules.ignore_sender_and_reject_pending``).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from selko.db import codec, errors
from selko.db.connection import Database, Tx
from selko.db.events import (
    _enqueue_calendar_work,
    jtext,
    pg_bool,
    pg_timestamp,
    pg_uuid,
)

_HASH_FIELDS = (
    "id", "event_id", "user_id", "source_id", "kind", "status", "change_set",
    "event_snapshot_before", "resolution_reason", "created_at", "resolved_at", "updated_at",
)


def event_change_proposal_hash(proposal: dict[str, Any]) -> str:
    """sha256 over the proposal's identity, payload and timestamps.

    Not byte-compatible with the Postgres hash (that one hashed jsonb's text);
    no hash is persisted, so only values computed by this function are compared.
    """
    payload = {key: proposal.get(key) for key in _HASH_FIELDS}
    return hashlib.sha256(codec.to_json(payload).encode("utf-8")).hexdigest()  # type: ignore[union-attr]


def _row(tx: Tx, table: str, sql: str, params: Any) -> dict[str, Any] | None:
    return tx.schema.decode(table, tx.execute(sql, params).fetchone())


def _owned_event(tx: Tx, event_id: str, user_id: str, message: str) -> dict[str, Any]:
    event = _row(tx, "events", "SELECT * FROM events WHERE id = ? AND user_id = ?", (event_id, user_id))
    if event is None:
        raise errors.NotOwned(message)
    return event


def _lock_owned_pending_proposal(
    tx: Tx, event_id: str, user_id: str, proposal_id: str, expected_hash: str | None
) -> dict[str, Any]:
    proposal = _row(
        tx, "event_change_proposals",
        "SELECT p.* FROM event_change_proposals p JOIN events e ON e.id = p.event_id "
        "WHERE p.id = ? AND p.event_id = ? AND p.user_id = ?",
        (proposal_id, event_id, user_id),
    )
    if proposal is None or proposal["status"] != "pending":
        raise errors.ProposalStateError(f"proposal {proposal_id} is not an owned pending proposal")
    if expected_hash is not None and event_change_proposal_hash(proposal) != expected_hash:
        raise errors.StaleProposal(f"proposal {proposal_id} changed before transition")
    return proposal


def _ids(user_id: Any, event_id: Any, proposal_id: Any) -> tuple[str, str, str]:
    return codec.to_id(user_id), pg_uuid(str(event_id)), pg_uuid(str(proposal_id))  # type: ignore[return-value]


def _bool(value: bool | None) -> int | None:
    return None if value is None else int(bool(value))


# ---------------------------------------------------------------------------
# 44 apply_event_change_proposal
# ---------------------------------------------------------------------------


def apply_event_change_proposal(
    db: Database,
    user_id: str,
    event_id: str,
    proposal_id: str,
    expected_hash: str | None,
    title: str | None,
    start_datetime: datetime | str | None,
    end_datetime: datetime | str | None,
    all_day: bool | None,
    location: str | None,
    description: str | None,
    importance: str | None,
    review_status: str | None,
    calendar_sync_action: str | None,
) -> dict[str, Any]:
    """Apply a pending proposal: write the event, mark it applied, queue calendar work if active."""
    user_id, event_id, proposal_id = _ids(user_id, event_id, proposal_id)
    start, end = pg_timestamp(start_datetime), pg_timestamp(end_datetime)
    item: dict[str, Any] | None = None
    with db.write() as tx:
        _owned_event(tx, event_id, user_id, f"event {event_id} is not owned by user {user_id}")
        proposal = _lock_owned_pending_proposal(tx, event_id, user_id, proposal_id, expected_hash)
        if ((review_status is not None and review_status not in ("active", "cancelled"))
                or (calendar_sync_action is not None and calendar_sync_action not in ("upsert", "cancel"))):
            raise errors.InvalidArgument("invalid proposal application state")
        tx.execute(
            "UPDATE events SET title = ?, start_datetime = ?, end_datetime = ?, all_day = ?, "
            "location = ?, description = ?, importance = ?, review_status = ?, updated_at = ? WHERE id = ?",
            (title, start, end, _bool(all_day), location, description, importance, review_status,
             tx.now_text, event_id),
        )
        tx.execute(
            "UPDATE event_change_proposals SET status = 'applied', resolution_reason = 'user_applied', "
            "resolved_at = ?, updated_at = ? WHERE id = ?",
            (tx.now_text, tx.now_text, proposal["id"]),
        )
        if review_status == "active":
            desired = None if calendar_sync_action == "cancel" else {
                "title": title, "start_datetime": start, "end_datetime": end, "all_day": all_day,
                "location": location, "description": description, "importance": importance,
            }
            item = _enqueue_calendar_work(tx, event_id, user_id, calendar_sync_action, desired, None, False)
    return {
        "event_id": event_id, "proposal_id": proposal["id"], "review_status": review_status,
        "calendar_work_id": item["id"] if item else None,
    }


# ---------------------------------------------------------------------------
# 45 reject_event_change_proposal
# ---------------------------------------------------------------------------


def reject_event_change_proposal_in_tx(
    tx: Tx,
    user_id: str,
    event_id: str,
    proposal_id: str,
    expected_hash: str | None,
    delete_event: bool | None,
    title: str | None,
    start_datetime: datetime | str | None,
    end_datetime: datetime | str | None,
    all_day: bool | None,
    location: str | None,
    description: str | None,
    importance: str | None,
    resolution_reason: str | None,
) -> dict[str, Any]:
    user_id, event_id, proposal_id = _ids(user_id, event_id, proposal_id)
    start, end = pg_timestamp(start_datetime), pg_timestamp(end_datetime)
    event = _owned_event(tx, event_id, user_id, f"event {event_id} is not owned by user {user_id}")
    proposal = _lock_owned_pending_proposal(tx, event_id, user_id, proposal_id, expected_hash)
    if resolution_reason is not None and resolution_reason not in ("user_rejected", "repair_operator"):
        raise errors.InvalidArgument("invalid proposal rejection reason")
    if delete_event:
        if event["google_calendar_event_id"] is None or event["synced_at"] is not None:
            raise errors.InvalidArgument(f"event {event_id} is not an unsynced calendar-only proposal")
        tx.execute("DELETE FROM event_change_proposals WHERE id = ?", (proposal["id"],))
        # The event's other (resolved) proposals go with it, as Postgres's
        # cascade took them. Deleted first because SQLite checks the proposals'
        # ON DELETE RESTRICT on source_id per row, mid-cascade, where Postgres
        # let the cascade finish.
        tx.execute("DELETE FROM event_change_proposals WHERE event_id = ?", (event_id,))
        tx.execute("DELETE FROM events WHERE id = ?", (event_id,))
        return {"event_id": event_id, "proposal_id": proposal["id"], "status": "deleted"}
    # review_status is deliberately not written: a pending proposal's event is
    # already 'active' (the invariant), and rejecting the proposal resolves the
    # proposal, not the user's review decision.
    tx.execute(
        "UPDATE event_change_proposals SET status = 'rejected', resolution_reason = ?, "
        "resolved_at = ?, updated_at = ? WHERE id = ?",
        (resolution_reason, tx.now_text, tx.now_text, proposal["id"]),
    )
    tx.execute(
        "UPDATE events SET title = ?, start_datetime = ?, end_datetime = ?, all_day = ?, "
        "location = ?, description = ?, importance = ?, updated_at = ? WHERE id = ?",
        (title, start, end, _bool(all_day), location, description, importance, tx.now_text, event_id),
    )
    return {"event_id": event_id, "proposal_id": proposal["id"], "status": event["review_status"]}


def reject_event_change_proposal(db: Database, user_id: str, event_id: str, proposal_id: str,
                                 expected_hash: str | None, delete_event: bool | None,
                                 title: str | None, start_datetime: datetime | str | None,
                                 end_datetime: datetime | str | None, all_day: bool | None,
                                 location: str | None, description: str | None,
                                 importance: str | None, resolution_reason: str | None) -> dict[str, Any]:
    """Reject a pending proposal, restoring the given values (or deleting a calendar-only adopt)."""
    with db.write() as tx:
        return reject_event_change_proposal_in_tx(
            tx, user_id, event_id, proposal_id, expected_hash, delete_event, title, start_datetime,
            end_datetime, all_day, location, description, importance, resolution_reason,
        )


# ---------------------------------------------------------------------------
# 46 reopen_event_change_proposal
# ---------------------------------------------------------------------------


def reopen_event_change_proposal(
    db: Database,
    user_id: str,
    event_id: str,
    proposal_id: str,
    expected_hash: str | None = None,
    action: str | None = None,
    desired_event: dict[str, Any] | None = None,
    expected_provider_revision: str | None = None,
    force_overwrite: bool | None = False,
) -> dict[str, Any]:
    """Undo an applied proposal: restore its snapshot, put it back in the Changes lane."""
    user_id, event_id, proposal_id = _ids(user_id, event_id, proposal_id)
    item: dict[str, Any] | None = None
    with db.write() as tx:
        _owned_event(tx, event_id, user_id, f"event {event_id} is not owned")
        proposal = _row(
            tx, "event_change_proposals",
            "SELECT * FROM event_change_proposals WHERE id = ? AND event_id = ? AND user_id = ?",
            (proposal_id, event_id, user_id),
        )
        if proposal is None or proposal["status"] != "applied":
            raise errors.ProposalStateError(f"proposal {proposal_id} is not an applied proposal")
        if expected_hash is not None and event_change_proposal_hash(proposal) != expected_hash:
            raise errors.StaleProposal(f"proposal {proposal_id} changed before reopen")
        # Pending before the event is active: legal only because the invariant
        # is checked at commit, as Postgres deferred it.
        tx.execute(
            "UPDATE event_change_proposals SET status = 'pending', resolution_reason = NULL, "
            "resolved_at = NULL, updated_at = ? WHERE id = ?",
            (tx.now_text, proposal["id"]),
        )
        snap = proposal["event_snapshot_before"]
        start, end = jtext(snap, "start_datetime"), jtext(snap, "end_datetime")
        all_day = pg_bool(jtext(snap, "all_day"))
        tx.execute(
            "UPDATE events SET title = ?, start_datetime = ?, end_datetime = ?, all_day = ?, "
            "location = ?, description = ?, importance = COALESCE(?, importance), "
            "review_status = 'active', updated_at = ? WHERE id = ?",
            (jtext(snap, "title"), pg_timestamp(start) if start != "" else None,
             pg_timestamp(end) if end != "" else None, int(all_day) if all_day is not None else 0,
             jtext(snap, "location"), jtext(snap, "description"), jtext(snap, "importance"),
             tx.now_text, event_id),
        )
        if action is not None:
            item = _enqueue_calendar_work(tx, event_id, user_id, action, desired_event,
                                          expected_provider_revision, force_overwrite)
    return {"event_id": event_id, "proposal_id": proposal["id"], "status": "active", "calendar_work": item}


# ---------------------------------------------------------------------------
# 47 resolve_event_change_proposal (operator repair only)
# ---------------------------------------------------------------------------


def resolve_event_change_proposal(db: Database, user_id: str, event_id: str, proposal_id: str,
                                  expected_hash: str | None, resolution_reason: str | None) -> dict[str, Any]:
    """Close a ``closed_legacy`` proposal as rejected (scripts/repair_review_queue_integrity.py)."""
    user_id, event_id, proposal_id = _ids(user_id, event_id, proposal_id)
    with db.write() as tx:
        proposal = _row(
            tx, "event_change_proposals",
            "SELECT p.* FROM event_change_proposals p JOIN events e ON e.id = p.event_id "
            "WHERE p.id = ? AND p.event_id = ? AND p.user_id = ?",
            (proposal_id, event_id, user_id),
        )
        if proposal is None or proposal["status"] != "closed_legacy":
            raise errors.ProposalStateError(f"proposal {proposal_id} is not an owned closed legacy proposal")
        if expected_hash is not None and event_change_proposal_hash(proposal) != expected_hash:
            raise errors.StaleProposal(f"proposal {proposal_id} changed before resolution")
        if resolution_reason is not None and resolution_reason not in (
            "historical_proposal_cleanup", "operator_confirmed_rejection"
        ):
            raise errors.InvalidArgument("invalid proposal resolution reason")
        tx.execute(
            "UPDATE event_change_proposals SET status = 'rejected', resolution_reason = ?, "
            "resolved_at = ?, updated_at = ? WHERE id = ?",
            (resolution_reason, tx.now_text, tx.now_text, proposal["id"]),
        )
    return {"event_id": event_id, "proposal_id": proposal["id"], "status": "rejected"}


# ---------------------------------------------------------------------------
# Reads (routes/events.py, services/events.py)
# ---------------------------------------------------------------------------


def get_pending(db: Database, user_id: str, event_id: str) -> dict[str, Any] | None:
    """The event's one pending proposal (unique by index), or None."""
    row = db.query_one(
        "SELECT * FROM event_change_proposals WHERE event_id = ? AND user_id = ? AND status = 'pending'",
        (codec.to_id(event_id), codec.to_id(user_id)),
    )
    return db.schema.decode("event_change_proposals", row)


def get(db: Database, user_id: str, event_id: str, proposal_id: str) -> dict[str, Any] | None:
    row = db.query_one(
        "SELECT * FROM event_change_proposals WHERE id = ? AND event_id = ? AND user_id = ?",
        (codec.to_id(proposal_id), codec.to_id(event_id), codec.to_id(user_id)),
    )
    return db.schema.decode("event_change_proposals", row)


def latest_applied(db: Database, user_id: str, event_id: str) -> dict[str, Any] | None:
    """The applied proposal with the latest ``resolved_at`` (Postgres DESC: NULLs first)."""
    row = db.query_one(
        "SELECT * FROM event_change_proposals WHERE event_id = ? AND user_id = ? AND status = 'applied' "
        "ORDER BY resolved_at IS NULL DESC, resolved_at DESC LIMIT 1",
        (codec.to_id(event_id), codec.to_id(user_id)),
    )
    return db.schema.decode("event_change_proposals", row)


__all__ = [
    "apply_event_change_proposal", "event_change_proposal_hash", "get", "get_pending",
    "latest_applied", "reject_event_change_proposal", "reject_event_change_proposal_in_tx",
    "reopen_event_change_proposal", "resolve_event_change_proposal",
]
