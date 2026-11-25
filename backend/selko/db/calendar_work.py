"""Calendar work items: the single owner of calendar delivery, and its routing.

Ports of the Postgres functions in docs/specs/sqlite-single-process/02-data-layer.md
§2.4 (22-38), plus the inline asyncpg statements and supabase-py table calls
that touch ``calendar_work_items`` and ``calendar_sync_log`` (§3.4, §3.13, §4).

A work item owns action, generation, attempts, lease and failure for one event's
calendar write. Every transition after the claim is fenced on
``(status='processing', locked_by, generation)``: a worker whose lease was
superseded or reclaimed gets ``False`` / ``{"fenced": True}`` and changes
nothing, exactly as the Postgres functions did.

Routing (which calendar a write goes to) used to be computed per candidate row
in SQL (``calendar_write_provider`` / ``calendar_integration_writable``), with
Python twins in ``services/calendar_providers.py``. There is now one
implementation: the twins, called on a batch of candidates read inside the
claim's transaction (§5.1).

Not ported, because nothing calls them (§2.4): ``claim_calendar_work`` (25),
``heartbeat_calendar_work`` (29) and the SQL ``unlock_expired_event_locks``
(30); the Python ``unlock_expired_event_locks`` only counts, which is
`count_expired_leases`. ``calendar_work_item_owner_check`` (38) is the
trigger pair in ``0001_initial.sql``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from selko.db import errors
from selko.db.codec import new_id, to_id, to_json, to_timestamp
from selko.db.connection import Database, Tx
from selko.services.calendar_providers import (
    GOOGLE,
    OUTLOOK,
    provider_of_id,
    resolve_target_provider,
    writable_providers,
)

ACTIONS = ("upsert", "cancel")
DECLINED = ("rejected", "cancelled")
#: Candidates routed per batch by the claim; the loop continues until the
#: queue is exhausted, as the Postgres scan did.
CLAIM_SCAN = 50
#: The wake-up the calendar workers wait for (WorkSignals.WORK_TYPES).
WORK_TYPE = "event_approved"

_SYNC_SNAPSHOT_ACTIONS = ("created", "updated")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _rows(source: Database | Tx, sql: str, params: Sequence[Any] = ()) -> list[Any]:
    if isinstance(source, Tx):
        return source.execute(sql, tuple(params)).fetchall()
    return source.query(sql, tuple(params))


def _left(value: str | None, n: int) -> str | None:
    """Postgres ``left(text, n)``: NULL stays NULL."""
    return None if value is None else value[:n]


def _timestamp_arg(value: datetime | str) -> str:
    """A ``timestamptz`` argument: zone-less input is UTC, as in a UTC session."""
    if isinstance(value, str):
        text = value.strip()
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    else:
        parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return to_timestamp(parsed)  # type: ignore[return-value]


def _decode_item(source: Database | Tx, row: Any) -> dict[str, Any] | None:
    return source.schema.decode("calendar_work_items", row)


def _owned_event(tx: Tx, event_id: str, user_id: str) -> dict[str, Any]:
    row = tx.execute(
        "SELECT * FROM events WHERE id = ? AND user_id = ?", (event_id, user_id)
    ).fetchone()
    if row is None:
        raise errors.NotOwned(f"event {event_id} is not owned by user {user_id}")
    return tx.schema.decode("events", row)  # type: ignore[return-value]


def _integrations_by_user(
    source: Database | Tx, user_ids: Iterable[str]
) -> dict[str, list[dict[str, Any]]]:
    ids = sorted(set(user_ids))
    out: dict[str, list[dict[str, Any]]] = {uid: [] for uid in ids}
    if not ids:
        return out
    for row in _rows(
        source,
        "SELECT user_id, provider, status, scopes FROM integrations "
        "WHERE user_id IN (SELECT value FROM json_each(?))",
        (to_json(ids),),
    ):
        out[row["user_id"]].append(source.schema.decode("integrations", row))  # type: ignore[arg-type]
    return out


# ---------------------------------------------------------------------------
# routing: calendar_write_provider (34), calendar_integration_writable (35);
# calendar_provider_of_id (36) and outlook_scopes_allow_calendar (37) are the
# calendar_providers functions themselves.
# ---------------------------------------------------------------------------


def write_provider_for(
    existing_event_id: str | None,
    target_calendar_id: str | None,
    integrations: list[dict[str, Any]],
) -> str:
    """``calendar_write_provider`` on already-loaded rows.

    An event already in a calendar stays there (any non-NULL id, even ''),
    then the target calendar's provider, then Google if writable, then
    Outlook if writable, else Google.
    """
    if existing_event_id is not None:
        return provider_of_id(existing_event_id)
    return resolve_target_provider(target_calendar_id, integrations)


def integration_writable(integrations: list[dict[str, Any]], provider: str | None) -> bool:
    """``calendar_integration_writable`` on already-loaded rows."""
    return provider in writable_providers(integrations)


def calendar_write_provider(db: Database | Tx, user_id: str, event_id: str) -> str:
    user_id = to_id(user_id)  # type: ignore[assignment]
    event_id = to_id(event_id)  # type: ignore[assignment]
    event = _rows(db, "SELECT google_calendar_event_id FROM events WHERE id = ?", (event_id,))
    existing = event[0]["google_calendar_event_id"] if event else None
    settings = _rows(
        db, "SELECT target_calendar_id FROM user_calendar_settings WHERE user_id = ?", (user_id,)
    )
    target = settings[0]["target_calendar_id"] if settings else None
    return write_provider_for(existing, target, _integrations_by_user(db, [user_id])[user_id])


# ---------------------------------------------------------------------------
# enqueue (22, 23) and the callers that wrap it (31, 32, 33)
# ---------------------------------------------------------------------------


def _enqueue_calendar_work(
    tx: Tx,
    event_id: str,
    user_id: str,
    action: str | None,
    desired_event: Any = None,
    expected_provider_revision: str | None = None,
    force_overwrite: bool | None = False,
) -> dict[str, Any]:
    """Supersede the event's active item and queue a new generation, in the caller's ``tx``.

    Never changes ``events.review_status``: a caller reviving a declined
    event sets it first, in the same transaction.
    """
    event_id = to_id(event_id)  # type: ignore[assignment]
    user_id = to_id(user_id)  # type: ignore[assignment]
    # Postgres: `p_action NOT IN (...)` is NULL for a NULL action, so a NULL
    # action passes this check and fails on the NOT NULL insert below.
    if action is not None and action not in ACTIONS:
        raise errors.InvalidArgument(f"invalid calendar work action {action}")
    if action == "upsert" and desired_event is None:
        raise errors.InvalidArgument("upsert calendar work requires desired_event")
    event = _owned_event(tx, event_id, user_id)
    if action == "upsert" and event["review_status"] in DECLINED:
        raise errors.InvalidArgument(
            f"cannot queue calendar upsert for {event['review_status']} event {event_id}"
        )
    generation = tx.execute(
        "SELECT COALESCE(max(generation), 0) + 1 FROM calendar_work_items WHERE event_id = ?",
        (event_id,),
    ).fetchone()[0]
    # Order matters: the partial unique index allows one active item per event.
    tx.execute(
        "UPDATE calendar_work_items SET status = 'superseded', updated_at = ?, completed_at = ? "
        "WHERE event_id = ? AND status IN ('pending', 'processing')",
        (tx.now_text, tx.now_text, event_id),
    )
    row = tx.execute(
        "INSERT INTO calendar_work_items (id, event_id, user_id, action, generation, status, "
        "desired_event, provider_event_id, expected_provider_revision, force_overwrite, "
        "attempts, max_attempts, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, 0, 3, ?, ?) RETURNING *",
        (
            new_id(), event_id, user_id, action, generation,
            to_json(desired_event), event["google_calendar_event_id"],
            expected_provider_revision, int(bool(force_overwrite)),
            tx.now_text, tx.now_text,
        ),
    ).fetchone()
    tx.execute("UPDATE events SET updated_at = ? WHERE id = ?", (tx.now_text, event_id))
    # Postgres never sent this (02 §0.3); the calendar workers wait for it.
    tx.emit_work(WORK_TYPE)
    return _decode_item(tx, row)  # type: ignore[return-value]


def enqueue_calendar_work(
    db: Database,
    user_id: str,
    event_id: str,
    action: str | None,
    desired_event: Any = None,
    expected_provider_revision: str | None = None,
    force_overwrite: bool | None = False,
) -> dict[str, Any]:
    """23: returns ``{id, event_id, generation, status, action}``."""
    with db.write() as tx:
        item = _enqueue_calendar_work(
            tx, event_id, user_id, action, desired_event, expected_provider_revision, force_overwrite
        )
    return {key: item[key] for key in ("id", "event_id", "generation", "status", "action")}


def undo_event_and_enqueue_calendar_work(
    db: Database,
    user_id: str,
    event_id: str,
    action: str | None = None,
    desired_event: Any = None,
    expected_provider_revision: str | None = None,
    force_overwrite: bool | None = False,
) -> dict[str, Any]:
    """33: optionally queue calendar work, then return the event to review."""
    event_id = to_id(event_id)  # type: ignore[assignment]
    user_id = to_id(user_id)  # type: ignore[assignment]
    item: dict[str, Any] | None = None
    with db.write() as tx:
        _owned_event(tx, event_id, user_id)
        if action is not None:
            item = _enqueue_calendar_work(
                tx, event_id, user_id, action, desired_event,
                expected_provider_revision, force_overwrite,
            )
        tx.execute(
            "UPDATE events SET review_status = 'pending_review', updated_at = ? WHERE id = ?",
            (tx.now_text, event_id),
        )
    return {
        "status": "pending_review",
        "work_item_id": item["id"] if item else None,
        "generation": item["generation"] if item else None,
    }


# ---------------------------------------------------------------------------
# the claim (24)
# ---------------------------------------------------------------------------


def _first_routable(
    tx: Tx, where: str, order: str, params: tuple[Any, ...], providers: Sequence[str] | None
) -> tuple[dict[str, Any], str] | None:
    """The first candidate (in ``order``) whose provider is allowed and writable."""
    offset = 0
    while True:
        batch = tx.execute(
            "SELECT w.*, e.google_calendar_event_id AS _event_calendar_id, "
            "s.target_calendar_id AS _target_calendar_id "
            "FROM calendar_work_items w "
            "LEFT JOIN events e ON e.id = w.event_id "
            "LEFT JOIN user_calendar_settings s ON s.user_id = w.user_id "
            f"WHERE {where} ORDER BY {order}, w.rowid LIMIT ? OFFSET ?",
            (*params, CLAIM_SCAN, offset),
        ).fetchall()
        if not batch:
            return None
        integrations = _integrations_by_user(tx, (row["user_id"] for row in batch))
        for row in batch:
            user_integrations = integrations[row["user_id"]]
            provider = row["provider"] or write_provider_for(
                row["_event_calendar_id"], row["_target_calendar_id"], user_integrations
            )
            if providers is not None and provider not in providers:
                continue
            if not integration_writable(user_integrations, provider):
                continue
            return dict(row), provider
        if len(batch) < CLAIM_SCAN:
            return None
        offset += CLAIM_SCAN


def claim_calendar_work_item(
    db: Database,
    worker_id: str,
    lease_seconds: int = 300,
    providers: Sequence[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Claim the oldest claimable item whose calendar is writable and allowed.

    ``providers`` are the providers whose circuit is closed (None: all). The
    pending pass runs before the expired-lease pass, as in Postgres. Returns
    ``(item, event)`` read in the same transaction, or None.
    """
    providers = list(providers) if providers is not None else None
    with db.write() as tx:
        found = _first_routable(
            tx,
            "w.status = 'pending' AND w.attempts < w.max_attempts "
            "AND (w.next_retry_at IS NULL OR w.next_retry_at <= ?)",
            "w.created_at ASC",
            (tx.now_text,),
            providers,
        )
        if found is None:
            found = _first_routable(
                tx,
                "w.status = 'processing' AND w.locked_until IS NOT NULL AND w.locked_until < ? "
                "AND w.attempts < w.max_attempts",
                "w.locked_until ASC",
                (tx.now_text,),
                providers,
            )
            if found is not None:
                tx.execute(
                    "UPDATE calendar_work_items SET status = 'pending', locked_by = NULL, "
                    "locked_until = NULL, updated_at = ? WHERE id = ?",
                    (tx.now_text, found[0]["id"]),
                )
        if found is None:
            return None
        candidate, provider = found
        row = tx.execute(
            "UPDATE calendar_work_items SET status = 'processing', locked_by = ?, "
            "locked_until = ?, attempts = attempts + 1, provider = ?, updated_at = ? "
            "WHERE id = ? RETURNING *",
            (worker_id, tx.ts(max(int(lease_seconds), 1)), provider, tx.now_text, candidate["id"]),
        ).fetchone()
        item = _decode_item(tx, row)
        tx.execute("UPDATE events SET updated_at = ? WHERE id = ?", (tx.now_text, item["event_id"]))  # type: ignore[index]
        event = tx.schema.decode(
            "events",
            tx.execute("SELECT * FROM events WHERE id = ?", (item["event_id"],)).fetchone(),  # type: ignore[index]
        )
    return item, event  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# fenced transitions (26, 27, 28)
# ---------------------------------------------------------------------------


def _leased(tx: Tx, item_id: str, worker_id: str, generation: int) -> dict[str, Any] | None:
    row = tx.execute("SELECT * FROM calendar_work_items WHERE id = ?", (to_id(item_id),)).fetchone()
    if (
        row is None
        or row["status"] != "processing"
        or row["locked_by"] != worker_id  # IS DISTINCT FROM: NULL equals NULL
        or generation is None
        or row["generation"] != int(generation)
    ):
        return None
    return _decode_item(tx, row)


def complete_calendar_work(
    db: Database,
    item_id: str,
    worker_id: str,
    generation: int,
    provider_event_id: str | None,
    provider_revision: str | None = None,
) -> bool:
    """26: the provider write landed. False when the lease is not this worker's."""
    with db.write() as tx:
        item = _leased(tx, item_id, worker_id, generation)
        if item is None:
            return False
        is_cancel = 1 if item["action"] == "cancel" else 0
        # Only a cancel of an *active* event makes it cancelled: an unsync
        # also queues 'cancel' but has already set pending_review.
        tx.execute(
            "UPDATE events SET "
            "google_calendar_event_id = CASE WHEN ? THEN NULL ELSE COALESCE(?, google_calendar_event_id) END, "
            "synced_at = CASE WHEN ? THEN NULL ELSE ? END, "
            "review_status = CASE WHEN ? AND review_status = 'active' THEN 'cancelled' ELSE review_status END, "
            "updated_at = ? WHERE id = ?",
            (is_cancel, provider_event_id, is_cancel, tx.now_text, is_cancel, tx.now_text, item["event_id"]),
        )
        tx.execute(
            "UPDATE calendar_work_items SET status = 'succeeded', "
            "provider_event_id = COALESCE(?, provider_event_id), "
            "expected_provider_revision = COALESCE(?, expected_provider_revision), "
            "locked_by = NULL, locked_until = NULL, updated_at = ?, completed_at = ? WHERE id = ?",
            (provider_event_id, provider_revision, tx.now_text, tx.now_text, item["id"]),
        )
    return True


def retry_delay_seconds(attempts: int) -> int:
    """``least(1800, greatest(60, 60 * power(2, least(attempts - 1, 5))::integer))``."""
    return min(1800, max(60, 60 * round(2.0 ** min(attempts - 1, 5))))


def fail_calendar_work(
    db: Database,
    item_id: str,
    worker_id: str,
    generation: int,
    error_code: str | None,
    error_detail: str | None = None,
    retryable: bool = True,
) -> dict[str, Any]:
    """27: retry with backoff, or end as ``failed`` (budget spent) / ``blocked`` (not retryable)."""
    with db.write() as tx:
        item = _leased(tx, item_id, worker_id, generation)
        if item is None:
            return {"fenced": True}
        if retryable and item["attempts"] < item["max_attempts"]:
            status = "pending"
            tx.execute(
                "UPDATE calendar_work_items SET status = 'pending', failure_code = ?, "
                "failure_detail = ?, locked_by = NULL, locked_until = NULL, next_retry_at = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    _left(error_code, 100), _left(error_detail, 500),
                    tx.ts(retry_delay_seconds(item["attempts"])), tx.now_text, item["id"],
                ),
            )
        else:
            status = "failed" if retryable else "blocked"
            tx.execute(
                "UPDATE calendar_work_items SET status = ?, failure_code = ?, failure_detail = ?, "
                "locked_by = NULL, locked_until = NULL, completed_at = ?, updated_at = ? WHERE id = ?",
                (status, _left(error_code, 100), _left(error_detail, 500), tx.now_text, tx.now_text, item["id"]),
            )
        tx.execute("UPDATE events SET updated_at = ? WHERE id = ?", (tx.now_text, item["event_id"]))
    return {"fenced": False, "status": status}


def defer_calendar_work(
    db: Database,
    item_id: str,
    worker_id: str,
    generation: int,
    next_retry_at: datetime | str,
    detail: str | None = "calendar quota exceeded",
) -> bool:
    """28: release the lease until ``next_retry_at`` without spending the attempt."""
    retry_at = _timestamp_arg(next_retry_at) if next_retry_at is not None else None
    with db.write() as tx:
        item = _leased(tx, item_id, worker_id, generation)
        if item is None:
            return False
        tx.execute(
            "UPDATE calendar_work_items SET status = 'pending', attempts = max(attempts - 1, 0), "
            "failure_code = 'calendar_quota', failure_detail = ?, locked_by = NULL, "
            "locked_until = NULL, next_retry_at = ?, updated_at = ? WHERE id = ?",
            (_left(detail, 500), retry_at, tx.now_text, item["id"]),
        )
        tx.execute("UPDATE events SET updated_at = ? WHERE id = ?", (tx.now_text, item["event_id"]))
    return True


# ---------------------------------------------------------------------------
# reads that were inline SQL or table calls
# ---------------------------------------------------------------------------


def get_leased_item(
    db: Database, item_id: str, worker_id: str, generation: int
) -> dict[str, Any] | None:
    """``_resolve_calendar_work_item``: the exact leased row, or None."""
    row = db.query_one(
        "SELECT * FROM calendar_work_items WHERE id = ? AND status = 'processing' "
        "AND locked_by = ? AND generation = ?",
        (to_id(item_id), worker_id, int(generation)),
    )
    return _decode_item(db, row)


# ---------------------------------------------------------------------------
# calendar_sync_log (services/calendars.py:711, :1096)
# ---------------------------------------------------------------------------


def log_calendar_sync(
    db: Database,
    user_id: str,
    event_id: str,
    google_calendar_event_id: str,
    action: str,
    snapshot: Any,
) -> str:
    """Append one audit row (``_log_sync``). Returns its id.

    The row's ``user_id`` is the event's owner; ``NotOwned`` when the event
    is not the caller's.
    """
    row_id = new_id()
    with db.write() as tx:
        cur = tx.execute(
            "INSERT INTO calendar_sync_log (id, event_id, user_id, google_calendar_event_id, "
            "action, snapshot_synced, synced_at) "
            "SELECT ?, id, user_id, ?, ?, ?, ? FROM events WHERE id = ? AND user_id = ?",
            (row_id, google_calendar_event_id, action, to_json(snapshot), tx.now_text,
             to_id(event_id), to_id(user_id)),
        )
        if cur.rowcount != 1:
            raise errors.NotOwned(f"event {event_id} is not owned by user {user_id}")
    return row_id


def latest_sync_snapshot(
    db: Database,
    user_id: str,
    event_id: str,
    actions: Sequence[str] = _SYNC_SNAPSHOT_ACTIONS,
) -> dict[str, Any] | None:
    """``get_latest_sync_snapshot``: the newest snapshot for ``actions``, if it is an object."""
    row = db.query_one(
        "SELECT snapshot_synced FROM calendar_sync_log WHERE user_id = ? AND event_id = ? "
        "AND action IN (SELECT value FROM json_each(?)) ORDER BY synced_at DESC, rowid DESC LIMIT 1",
        (to_id(user_id), to_id(event_id), to_json(list(actions))),
    )
    if row is None:
        return None
    snapshot = db.schema.decode("calendar_sync_log", row)["snapshot_synced"]  # type: ignore[index]
    return snapshot if isinstance(snapshot, dict) else None


def queue_event_cancellation(db: Database, user_id: str, event_id: str) -> dict[str, Any]:
    """31: the operator repair's cancellation transition."""
    event_id = to_id(event_id)  # type: ignore[assignment]
    user_id = to_id(user_id)  # type: ignore[assignment]
    with db.write() as tx:
        event = _owned_event(tx, event_id, user_id)
        if event["review_status"] == "cancelled":
            return {"event_id": event_id, "status": "cancelled", "already_cancelled": True}
        processing = tx.execute(
            "SELECT 1 FROM calendar_work_items WHERE event_id = ? AND status = 'processing' LIMIT 1",
            (event_id,),
        ).fetchone()
        if event["review_status"] == "rejected" or processing is not None:
            raise errors.InvalidArgument(f"event {event_id} cannot be cancelled in its current state")
        if event["review_status"] == "pending_review":
            tx.execute(
                "UPDATE events SET review_status = 'active', updated_at = ? WHERE id = ?",
                (tx.now_text, event_id),
            )
        item = _enqueue_calendar_work(tx, event_id, user_id, "cancel", None, None, False)
    return {
        "event_id": event_id, "status": "cancel_queued", "work_item_id": item["id"],
        "generation": item["generation"], "already_cancelled": False,
    }


__all__ = [
    "queue_event_cancellation",
    "GOOGLE",
    "OUTLOOK",
    "calendar_write_provider",
    "claim_calendar_work_item",
    "complete_calendar_work",
    "defer_calendar_work",
    "enqueue_calendar_work",
    "fail_calendar_work",
    "get_leased_item",
    "integration_writable",
    "latest_sync_snapshot",
    "log_calendar_sync",
    "retry_delay_seconds",
    "undo_event_and_enqueue_calendar_work",
    "write_provider_for",
]
