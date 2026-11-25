"""Reconnect recovery: the five Postgres functions behind ``integration_recoveries``.

Ports of ``complete_integration_reauthorization``,
``claim_integration_recovery``, ``requeue_calendar_recovery_batch``,
``refresh_waiting_calendar_recoveries`` and
``unlock_expired_integration_recoveries``
(docs/specs/sqlite-single-process/02-data-layer.md §2.7, functions 49-53),
plus the one read the web app makes of the table (the ConnectionRecovery card).

Each write is one ``db.write()`` transaction, as each Postgres function was one
statement-level transaction. ``FOR UPDATE SKIP LOCKED`` is unnecessary: the
single writer already holds the only write lock.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from selko.db import errors
from selko.db.codec import new_id, to_json, to_timestamp
from selko.db import calendar_work
from selko.db.connection import Database
from selko.services import calendar_providers

# integration_provider enum (a CHECK in 0001_initial.sql).
INTEGRATION_PROVIDERS = frozenset({"gmail", "google_photos", "google_calendar", "outlook"})

# Calendar work failures that a reconnect can heal.
OAUTH_FAILURE_CODES = ("oauth_required", "oauth_scope_required")

# The columns the web app's ConnectionRecovery card reads
# (frontend/src/lib/services/integrations.js:137).
RECOVERY_CARD_COLUMNS = (
    "id", "integration_id", "user_id", "provider", "status", "discovered_count",
    "completed_count", "remaining_count", "withdrawn_count", "error_detail", "requested_at",
)


# Provider routing (Postgres: outlook_scopes_allow_calendar,
# calendar_write_provider) has one implementation: db/calendar_work.py over
# services/calendar_providers.py.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 49 complete_integration_reauthorization
# ---------------------------------------------------------------------------


def complete_integration_reauthorization(
    db: Database,
    user_id: str,
    provider: str,
    access_token: str,
    refresh_token: str | None = None,
    token_expiry: Any = None,
    scopes: Iterable[str] | None = (),
    provider_email: str | None = None,
) -> str:
    """Upsert the credentials and, for a calendar grant, start a fresh recovery.

    Returns the integration id. A refresh token or provider email left out of a
    later consent never overwrites the stored one. For ``google_calendar``, and
    for an ``outlook`` grant that includes calendar read/write, every active
    recovery generation is superseded (its lease dies with it) and one new
    ``pending`` generation is created, in the same transaction.
    """
    if provider not in INTEGRATION_PROVIDERS:
        raise errors.InvalidArgument(f'invalid input value for enum integration_provider: "{provider}"')
    scope_list = [str(s) for s in scopes] if scopes is not None else None
    stored_scopes = to_json(scope_list if scope_list is not None else [])
    with db.write() as tx:
        row = tx.execute(
            """
            INSERT INTO integrations (
                id, user_id, provider, status, access_token, refresh_token,
                token_expiry, scopes, provider_email, created_at, updated_at
            ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (user_id, provider) DO UPDATE SET
                status = 'active',
                access_token = excluded.access_token,
                refresh_token = COALESCE(excluded.refresh_token, integrations.refresh_token),
                token_expiry = excluded.token_expiry,
                scopes = excluded.scopes,
                provider_email = COALESCE(excluded.provider_email, integrations.provider_email),
                updated_at = ?
            RETURNING id
            """,
            (
                new_id(), user_id, provider, access_token, refresh_token,
                to_timestamp(token_expiry), stored_scopes, provider_email,
                tx.now_text, tx.now_text, tx.now_text,
            ),
        ).fetchone()
        integration_id: str = row["id"]

        if provider == "google_calendar" or (
            provider == "outlook" and calendar_providers.outlook_scopes_allow_calendar(scope_list)
        ):
            tx.execute(
                """
                UPDATE integration_recoveries
                SET status = 'superseded', locked_by = NULL, locked_until = NULL, updated_at = ?
                WHERE integration_id = ? AND status IN ('pending', 'processing', 'waiting')
                """,
                (tx.now_text, integration_id),
            )
            tx.execute(
                """
                INSERT INTO integration_recoveries (
                    id, integration_id, user_id, provider, reason, status, requested_at, updated_at
                ) VALUES (?, ?, ?, ?, 'reauthorization', 'pending', ?, ?)
                """,
                (new_id(), integration_id, user_id, provider, tx.now_text, tx.now_text),
            )
    return integration_id


# ---------------------------------------------------------------------------
# 50 claim_integration_recovery
# ---------------------------------------------------------------------------


def claim_integration_recovery(
    db: Database, worker_id: str, lock_seconds: int = 300
) -> dict[str, Any] | None:
    """Lease the oldest claimable recovery generation, or return None.

    Claimable: ``pending`` or ``processing`` (a crashed worker's expired lease
    is reclaimed here, not only at startup), attempts left, no backoff in the
    future, no unexpired lock. Ordered by ``requested_at``.
    """
    with db.write() as tx:
        row = tx.execute(
            """
            UPDATE integration_recoveries SET
                status = 'processing',
                locked_by = :worker,
                locked_until = :until,
                attempts = attempts + 1,
                started_at = COALESCE(started_at, :now),
                updated_at = :now
            WHERE id = (
                SELECT id FROM integration_recoveries
                WHERE status IN ('pending', 'processing')
                  AND attempts < max_attempts
                  AND (next_retry_at IS NULL OR next_retry_at <= :now)
                  AND (locked_until IS NULL OR locked_until < :now)
                ORDER BY requested_at ASC, rowid ASC
                LIMIT 1
            )
            RETURNING *
            """,
            {"worker": worker_id, "until": tx.ts(max(lock_seconds, 1)), "now": tx.now_text},
        ).fetchone()
        return tx.schema.decode("integration_recoveries", row)


# ---------------------------------------------------------------------------
# 51 requeue_calendar_recovery_batch
# ---------------------------------------------------------------------------

_REQUEUE_CANDIDATES = f"""
SELECT w.id AS item_id, w.event_id, w.user_id, w.provider
FROM calendar_work_items w
JOIN events e ON e.id = w.event_id
WHERE e.user_id = ?
  AND w.failure_code IN ({", ".join(f"'{c}'" for c in OAUTH_FAILURE_CODES)})
  AND w.status IN ('failed', 'blocked')
  AND e.recovery_id IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM calendar_work_items newer
      WHERE newer.event_id = w.event_id AND newer.status IN ('pending', 'processing')
  )
ORDER BY w.event_id, w.rowid
"""


def requeue_calendar_recovery_batch(
    db: Database,
    recovery_id: str,
    worker_id: str,
    batch_size: int = 100,
    max_batches: int = 5,
) -> int:
    """Revive the OAuth-blocked calendar work of a claimed recovery and tag its events.

    Returns the number of events tagged, or -1 when ``worker_id`` no longer
    holds an unexpired lease on the recovery (expired, reclaimed or
    superseded). Only items whose write provider is the recovery's provider are
    revived; an item for an event with a newer active item is skipped. The
    recovery then moves to ``waiting`` with its lease released.
    """
    if batch_size < 0:
        raise errors.InvalidArgument("LIMIT must not be negative")
    with db.write() as tx:
        owner = tx.execute(
            """
            SELECT user_id, provider FROM integration_recoveries
            WHERE id = ? AND locked_by = ? AND locked_until > ?
            """,
            (recovery_id, worker_id, tx.now_text),
        ).fetchone()
        if owner is None:
            return -1
        user_id, provider = owner["user_id"], owner["provider"]

        tagged = 0
        batches = 0
        while True:
            batch: list[tuple[str, str]] = []
            if batch_size > 0:
                for cand in tx.execute(_REQUEUE_CANDIDATES, (user_id,)).fetchall():
                    item_provider = cand["provider"] or calendar_work.calendar_write_provider(
                        tx, cand["user_id"], cand["event_id"]
                    )
                    if item_provider == provider:
                        batch.append((cand["item_id"], cand["event_id"]))
                        if len(batch) >= batch_size:
                            break
            count = 0
            if batch:
                item_ids = [item_id for item_id, _ in batch]
                marks = ", ".join("?" for _ in item_ids)
                revived = tx.execute(
                    f"""
                    UPDATE calendar_work_items
                    SET status = 'pending', locked_by = NULL, locked_until = NULL,
                        next_retry_at = NULL, completed_at = NULL,
                        attempts = min(attempts, max_attempts - 1), updated_at = ?
                    WHERE id IN ({marks})
                    RETURNING event_id
                    """,
                    (tx.now_text, *item_ids),
                ).fetchall()
                event_ids = sorted({r["event_id"] for r in revived})
                if event_ids:
                    marks = ", ".join("?" for _ in event_ids)
                    count = tx.execute(
                        f"UPDATE events SET recovery_id = ?, updated_at = ? WHERE id IN ({marks})",
                        (recovery_id, tx.now_text, *event_ids),
                    ).rowcount
            tagged += count
            batches += 1
            if count < batch_size or batches >= max_batches:
                break

        tx.execute(
            """
            UPDATE integration_recoveries
            SET discovered_count = discovered_count + ?, requeued_count = requeued_count + ?,
                updated_at = ?
            WHERE id = ?
            """,
            (tagged, tagged, tx.now_text, recovery_id),
        )
        tx.execute(
            """
            UPDATE integration_recoveries SET status = 'waiting', remaining_count = (
                SELECT count(*) FROM calendar_work_items w JOIN events e ON e.id = w.event_id
                WHERE e.recovery_id = :id AND w.status IN ('pending', 'processing', 'failed', 'blocked')
            ), locked_by = NULL, locked_until = NULL, updated_at = :now
            WHERE id = :id
            """,
            {"id": recovery_id, "now": tx.now_text},
        )
        return tagged


# ---------------------------------------------------------------------------
# 52 refresh_waiting_calendar_recoveries
# ---------------------------------------------------------------------------


def refresh_waiting_calendar_recoveries(db: Database, batch_size: int = 20) -> int:
    """Recompute progress of up to ``batch_size`` waiting recoveries; finalize drained ones.

    A recovery with no tagged work left pending/processing becomes
    ``completed``, or ``completed_with_errors`` when any tagged item ended
    failed/blocked. Returns how many recoveries were processed.
    """
    if batch_size < 0:
        raise errors.InvalidArgument("LIMIT must not be negative")
    with db.write() as tx:
        ids = [
            r["id"]
            for r in tx.execute(
                "SELECT id FROM integration_recoveries WHERE status = 'waiting' "
                "ORDER BY updated_at, rowid LIMIT ?",
                (batch_size,),
            ).fetchall()
        ]
        for recovery_id in ids:
            counts = tx.execute(
                """
                SELECT
                    coalesce(sum(CASE WHEN w.status = 'succeeded' THEN 1 ELSE 0 END), 0) AS completed,
                    coalesce(sum(CASE WHEN w.status IN ('pending', 'processing') THEN 1 ELSE 0 END), 0) AS remaining,
                    coalesce(sum(CASE WHEN w.status IN ('failed', 'blocked') THEN 1 ELSE 0 END), 0) AS errored
                FROM calendar_work_items w JOIN events e ON e.id = w.event_id
                WHERE e.recovery_id = ?
                """,
                (recovery_id,),
            ).fetchone()
            if counts["remaining"] == 0:
                tx.execute(
                    """
                    UPDATE integration_recoveries SET status = ?, completed_count = ?,
                        remaining_count = 0, completed_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        "completed_with_errors" if counts["errored"] > 0 else "completed",
                        counts["completed"], tx.now_text, tx.now_text, recovery_id,
                    ),
                )
            else:
                tx.execute(
                    """
                    UPDATE integration_recoveries SET completed_count = ?, remaining_count = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (counts["completed"], counts["remaining"], tx.now_text, recovery_id),
                )
        return len(ids)


# ---------------------------------------------------------------------------
# 53 unlock_expired_integration_recoveries
# ---------------------------------------------------------------------------


def unlock_expired_integration_recoveries(db: Database) -> int:
    """Return processing recoveries whose lease expired to ``pending``; the count."""
    with db.write() as tx:
        return tx.execute(
            """
            UPDATE integration_recoveries
            SET status = 'pending', locked_by = NULL, locked_until = NULL, updated_at = ?
            WHERE status = 'processing' AND locked_until < ?
            """,
            (tx.now_text, tx.now_text),
        ).rowcount


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def latest_recovery(
    db: Database, user_id: str, provider: str = "google_calendar"
) -> dict[str, Any] | None:
    """The user's newest recovery generation for ``provider`` (the ConnectionRecovery card)."""
    row = db.query_one(
        f"SELECT {', '.join(RECOVERY_CARD_COLUMNS)} FROM integration_recoveries "
        "WHERE user_id = ? AND provider = ? ORDER BY requested_at DESC, rowid DESC LIMIT 1",
        (user_id, provider),
    )
    return db.schema.decode("integration_recoveries", row)


def outlook_scopes_allow_calendar(scopes: Iterable[str] | None) -> bool:
    """Whether a stored Microsoft grant includes calendar read/write (the routing twin)."""
    return calendar_providers.outlook_scopes_allow_calendar(list(scopes or ()))


__all__ = [
    "claim_integration_recovery",
    "complete_integration_reauthorization",
    "latest_recovery",
    "outlook_scopes_allow_calendar",
    "refresh_waiting_calendar_recoveries",
    "requeue_calendar_recovery_batch",
    "unlock_expired_integration_recoveries",
]
