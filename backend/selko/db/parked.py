"""Parked Google Photos ingestion: ``photos`` and ``scheduled_tasks``.

Google Photos is parked (CLAUDE.md; ``test_reachability.py``), and whether its
code is ported or deleted is an open owner decision
(docs/specs/sqlite-single-process/README.md). This module ports the call sites
that still have a caller, minimally and faithfully
(02-data-layer.md §2.12, §3.12).

==========================================  ===================================
Service call site                           db function
==========================================  ===================================
services/photos.py:47                       upsert_photo
  (save_photo_metadata)
services/photos.py:116                      complete_photo
  (complete_photo_processing)
services/photos.py:150, :174                fail_photo (one transaction)
  (fail_photo_processing)
services/photos.py:207                      get_photo
  (get_photo)
services/photos.py:235 ->                   unlock_expired_photo_locks
  unlock_expired_photo_locks() (§2.12 #61)
services/scheduled_tasks.py:56              enqueue_task
  (enqueue_scheduled_task)
services/scheduled_tasks.py:180 ->          unlock_expired_scheduled_tasks
  unlock_expired_scheduled_tasks() (#63)
==========================================  ===================================

Not ported, per §2.12/§3.12 (no production caller): ``claim_pending_photo``
(``services/photos.py:85``, #60), ``claim_next_scheduled_task``
(``services/scheduled_tasks.py:90``, #62), and ``scheduled_tasks.py:120``
(complete), ``:151`` (fail), ``:212`` (cleanup).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from selko.db import codec
from selko.db.connection import Database
from selko.db.errors import InvalidArgument, NotFound

_PHOTO_TIMESTAMPS = frozenset({
    "date_taken", "processed_at", "locked_until", "next_retry_at", "dead_letter_at", "created_at",
})
_PHOTO_COLUMNS = frozenset({
    "google_photo_id", "filename", "description", "mime_type", "date_taken", "width", "height",
    "location_latitude", "location_longitude", "location_display_name", "storage_path",
    "content_hash", "processing_status", "processing_error", "processed_at", "locked_until",
    "locked_by", "attempts", "max_attempts", "next_retry_at", "dead_letter_reason",
    "dead_letter_at",
})
_TASK_TYPES = frozenset({"photo_fetch", "email_fetch"})


def _timestamp(value: datetime | str | None) -> str | None:
    """Stored text for a moment; zone-less means UTC (Postgres's session zone)."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return codec.to_timestamp(value)


def retry_delay_seconds(attempt: int, base_delay: int = 60, max_delay: int = 3600) -> int:
    """``services/retry_utils.calculate_retry_delay``'s backoff, in seconds."""
    return min(base_delay * (2 ** (attempt - 1)), max_delay)


# ---------------------------------------------------------------------------
# photos
# ---------------------------------------------------------------------------


def upsert_photo(db: Database, user_id: str, photo_data: dict[str, Any]) -> dict[str, Any]:
    """Insert or update a photo on ``(user_id, google_photo_id)``; returns the stored row.

    Only the given columns are overwritten on conflict (PostgREST
    merge-duplicates); ``id``, ``created_at`` and the processing state of a
    re-fetched photo are kept unless ``photo_data`` names them.
    """
    data = {k: v for k, v in photo_data.items() if k not in {"user_id", "id"}}
    unknown = set(data) - _PHOTO_COLUMNS
    if unknown:
        raise InvalidArgument(f"unknown photos columns: {sorted(unknown)}")
    if not data.get("google_photo_id"):
        raise InvalidArgument("a photo needs a google_photo_id")
    for column in _PHOTO_TIMESTAMPS & data.keys():
        data[column] = _timestamp(data[column])
    uid = codec.to_id(user_id)
    with db.write() as tx:
        values = tx.schema.encode("photos", data)
        cols = ["id", "user_id", "created_at", *values]
        params = [codec.new_id(), uid, tx.now_text, *values.values()]
        update = ", ".join(f"{c} = excluded.{c}" for c in values if c != "google_photo_id") \
            or "google_photo_id = excluded.google_photo_id"
        row = tx.execute(
            f"INSERT INTO photos ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
            f"ON CONFLICT (user_id, google_photo_id) DO UPDATE SET {update} RETURNING *",
            params,
        ).fetchone()
        return tx.schema.decode("photos", row)  # type: ignore[return-value]


def complete_photo(db: Database, photo_id: str) -> int:
    """Mark a photo processed and release its lock. Worker-scoped. Returns rows changed."""
    with db.write() as tx:
        return tx.execute(
            "UPDATE photos SET processing_status = 'processed', processed_at = ?, "
            "locked_by = NULL, locked_until = NULL WHERE id = ?",
            (tx.now_text, codec.to_id(photo_id)),
        ).rowcount


def fail_photo(db: Database, photo_id: str, error: str) -> dict[str, Any]:
    """Record a failed attempt: back to pending with backoff, or dead-lettered.

    Retries while ``attempts < max_attempts`` (``next_retry_at`` = now +
    ``retry_delay_seconds(attempts)``); otherwise ``failed`` with the
    dead-letter columns set. Read and write are one transaction (two calls
    today). Returns ``attempts, max_attempts, should_retry, delay_seconds``
    for the caller's log line. Raises NotFound for an unknown photo
    (``.single()`` raised today). Worker-scoped.
    """
    pid = codec.to_id(photo_id)
    with db.write() as tx:
        row = tx.execute("SELECT attempts, max_attempts FROM photos WHERE id = ?", (pid,)).fetchone()
        if row is None:
            raise NotFound(f"photo {photo_id} not found")
        attempts, max_attempts = row["attempts"], row["max_attempts"]
        should_retry = attempts < max_attempts
        delay: int | None = None
        if should_retry:
            delay = retry_delay_seconds(attempts)
            tx.execute(
                "UPDATE photos SET processing_status = 'pending', processing_error = ?, "
                "locked_by = NULL, locked_until = NULL, next_retry_at = ? WHERE id = ?",
                (error, tx.ts(delay), pid),
            )
        else:
            tx.execute(
                "UPDATE photos SET processing_status = 'failed', processing_error = ?, "
                "locked_by = NULL, locked_until = NULL, dead_letter_reason = ?, dead_letter_at = ? "
                "WHERE id = ?",
                (error, error, tx.now_text, pid),
            )
    return {"attempts": attempts, "max_attempts": max_attempts,
            "should_retry": should_retry, "delay_seconds": delay}


def get_photo(db: Database, user_id: str, photo_id: str) -> dict[str, Any] | None:
    """One of the user's photos (``select *``), or None."""
    row = db.query_one(
        "SELECT * FROM photos WHERE id = ? AND user_id = ?",
        (codec.to_id(photo_id), codec.to_id(user_id)),
    )
    return db.schema.decode("photos", row)


def unlock_expired_photo_locks(db: Database) -> int:
    """``unlock_expired_photo_locks()``: expired ``processing`` claims back to pending."""
    with db.write() as tx:
        return tx.execute(
            "UPDATE photos SET processing_status = 'pending', locked_by = NULL, locked_until = NULL "
            "WHERE processing_status = 'processing' AND locked_until < ?",
            (tx.now_text,),
        ).rowcount


# ---------------------------------------------------------------------------
# scheduled_tasks
# ---------------------------------------------------------------------------


def enqueue_task(
    db: Database,
    user_id: str,
    task_type: str,
    payload: dict[str, Any],
    scheduled_at: datetime | str | None = None,
) -> str:
    """Insert a pending task (due now unless ``scheduled_at``); returns its id."""
    if task_type not in _TASK_TYPES:
        # The CHECK refuses it too; this names the problem.
        raise InvalidArgument(f"unknown task_type {task_type!r}")
    task_id = codec.new_id()
    with db.write() as tx:
        tx.execute(
            "INSERT INTO scheduled_tasks (id, user_id, task_type, payload, status, scheduled_at, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?, ?)",
            (task_id, codec.to_id(user_id), task_type, codec.to_json(payload),
             _timestamp(scheduled_at) if scheduled_at is not None else tx.now_text, tx.now_text),
        )
    return task_id


def users_with_open_tasks(db: Database, task_type: str) -> set[str]:
    """Users holding a pending or processing task of ``task_type``.

    Service-wide by design (the photo-fetch scheduler's de-duplication):
    user ids only.
    """
    rows = db.query(
        "SELECT DISTINCT user_id FROM scheduled_tasks "
        "WHERE task_type = ? AND status IN ('pending', 'processing')",
        (task_type,),
    )
    return {r[0] for r in rows}


def unlock_expired_scheduled_tasks(db: Database) -> int:
    """``unlock_expired_scheduled_tasks()``: expired ``processing`` tasks back to pending."""
    with db.write() as tx:
        return tx.execute(
            "UPDATE scheduled_tasks SET status = 'pending', locked_by = NULL, locked_until = NULL "
            "WHERE status = 'processing' AND locked_until < ?",
            (tx.now_text,),
        ).rowcount


__all__ = [
    "complete_photo",
    "enqueue_task",
    "fail_photo",
    "get_photo",
    "retry_delay_seconds",
    "unlock_expired_photo_locks",
    "unlock_expired_scheduled_tasks",
    "upsert_photo",
    "users_with_open_tasks",
]
