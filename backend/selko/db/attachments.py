"""Attachment work and rows.

Ports of ``claim_email_attachment`` and ``finish_email_attachment``
(docs/specs/sqlite-single-process/02-data-layer.md §2.3, 20-21), plus the
attachment reads and writes the services made through supabase-py and asyncpg
(§3.2, §3.8, §4: ``services/attachments.py``, ``event_processing``,
``EmailIngestionRepository.ensure_attachment_descriptors`` / ``attachment_readiness``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from selko.db import codec
from selko.db.connection import Database
from selko.db.errors import InvalidArgument

FINISH_STATES = ("stored", "unsupported", "retry", "dead_letter")
# What attachment_readiness treated as settled (the gate's complement).
SETTLED_STATES = frozenset({"stored", "unsupported", "dead_letter"})
# The columns services/attachments.save_attachment_metadata inserts.
INSERT_COLUMNS = (
    "email_id", "provider_attachment_id", "filename", "mime_type",
    "size_bytes", "storage_path", "content_hash",
)


def _decode(db: Database, row: Any) -> dict[str, Any] | None:
    return db.schema.decode("attachments", row)


# ---------------------------------------------------------------------------
# 20 claim_email_attachment
# ---------------------------------------------------------------------------


def claim_email_attachment(db: Database, worker_id: str, lease_seconds: int = 900) -> dict[str, Any] | None:
    """Claim the oldest attachment that is due; an expired ``processing`` lease is due too."""
    lease = max(lease_seconds, 1) if lease_seconds is not None else 1
    with db.write() as tx:
        row = tx.execute(
            "UPDATE attachments SET ingestion_status = 'processing', attempts = attempts + 1,"
            " locked_by = :worker, locked_until = :until"
            " WHERE id = (SELECT a.id FROM attachments a"
            "   WHERE a.ingestion_status IN ('pending', 'retry', 'processing')"
            "     AND a.attempts < a.max_attempts"
            "     AND (a.next_retry_at IS NULL OR a.next_retry_at <= :now)"
            "     AND (a.locked_until IS NULL OR a.locked_until <= :now)"
            "   ORDER BY a.created_at LIMIT 1)"
            " RETURNING *",
            {"worker": worker_id, "until": tx.ts(lease), "now": tx.now_text},
        ).fetchone()
        claimed = dict(row) if row is not None else None
    return _decode(db, claimed)


# ---------------------------------------------------------------------------
# 21 finish_email_attachment
# ---------------------------------------------------------------------------


def finish_email_attachment(
    db: Database, attachment_id: str, worker_id: str, status: str | None, error_code: str | None = None
) -> bool:
    """Fenced finish: only the worker holding the lock may set the outcome.

    A status outside `FINISH_STATES` raises `InvalidArgument`. As in Postgres,
    ``None`` passes that check (``NULL NOT IN (...)`` is not true) and then
    fails the NOT NULL constraint if the row matches. The email row is not
    touched, so no ``email_pending`` wake-up is sent (parity).
    """
    if status is not None and status not in FINISH_STATES:
        raise InvalidArgument("Invalid attachment terminal state")
    with db.write() as tx:
        return tx.execute(
            "UPDATE attachments SET ingestion_status = ?, ingestion_error_code = ?,"
            " locked_by = NULL, locked_until = NULL, next_retry_at = NULL"
            " WHERE id = ? AND locked_by = ?",
            (status, None if error_code is None else error_code[:100],
             codec.to_id(attachment_id), worker_id),
        ).rowcount > 0


# ---------------------------------------------------------------------------
# Rows (services/attachments.py, event_processing.py, email_ingestion.py)
# ---------------------------------------------------------------------------


def insert(db: Database, user_id: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """Insert an attachment row (``save_attachment_metadata``); returns the stored row.

    Only `INSERT_COLUMNS` are taken from ``row``; ``ingestion_status`` keeps
    its default ``pending``, as the PostgREST insert did.
    """
    unknown = set(row) - set(INSERT_COLUMNS) - {"user_id"}
    if unknown:
        raise InvalidArgument(f"unknown attachment columns: {sorted(unknown)}")
    values: dict[str, Any] = {c: row[c] for c in INSERT_COLUMNS if c in row}
    if "email_id" in values:
        values["email_id"] = codec.to_id(values["email_id"])
    with db.write() as tx:
        values.update(id=codec.new_id(), user_id=codec.to_id(user_id), created_at=tx.now_text)
        cols = list(values)
        stored = tx.execute(
            f"INSERT INTO attachments ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) RETURNING *",
            [values[c] for c in cols],
        ).fetchone()
        result = dict(stored)
    return _decode(db, result)  # type: ignore[return-value]


def get(db: Database, user_id: str, attachment_id: str) -> dict[str, Any] | None:
    row = db.query_one(
        "SELECT * FROM attachments WHERE id = ? AND user_id = ?",
        (codec.to_id(attachment_id), codec.to_id(user_id)),
    )
    return _decode(db, row)


def delete(db: Database, user_id: str, attachment_id: str) -> bool:
    """Delete the row; the caller removes the file after this commits."""
    with db.write() as tx:
        return tx.execute(
            "DELETE FROM attachments WHERE id = ? AND user_id = ?",
            (codec.to_id(attachment_id), codec.to_id(user_id)),
        ).rowcount > 0


def for_email(db: Database, email_id: str) -> list[dict[str, Any]]:
    """Every attachment of an email (worker-scoped, for extraction)."""
    rows = db.query(
        "SELECT * FROM attachments WHERE email_id = ? ORDER BY created_at, rowid",
        (codec.to_id(email_id),),
    )
    return [_decode(db, r) for r in rows]  # type: ignore[misc]


def store_result(
    db: Database,
    attachment_id: str,
    worker_id: str,
    *,
    storage_path: str,
    content_hash: str,
    size_bytes: int,
) -> bool:
    """Record a stored file on the attachment row, fenced on ``locked_by`` as today."""
    with db.write() as tx:
        return tx.execute(
            "UPDATE attachments SET storage_path = ?, content_hash = ?, size_bytes = ?"
            " WHERE id = ? AND locked_by = ?",
            (storage_path, content_hash, int(size_bytes), codec.to_id(attachment_id), worker_id),
        ).rowcount > 0


def ensure_descriptors(
    db: Database, email_id: str, user_id: str, descriptors: Iterable[Mapping[str, Any]]
) -> int:
    """Create pending attachment work for descriptors not yet recorded.

    Never resets an existing row. The fallbacks are those of
    ``EmailIngestionRepository.ensure_attachment_descriptors`` (Python ``or``
    chains, ``attachment_id`` accepted), which differ slightly from the save
    RPC's. One transaction instead of a select-then-insert loop. Returns the
    number of rows created.
    """
    created = 0
    with db.write() as tx:
        for descriptor in descriptors:
            provider_id = descriptor.get("provider_attachment_id") or descriptor.get("attachment_id")
            if not provider_id:
                continue
            created += tx.execute(
                "INSERT INTO attachments (id, user_id, email_id, provider_attachment_id, filename,"
                " mime_type, size_bytes, ingestion_status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)"
                " ON CONFLICT (email_id, provider_attachment_id)"
                " WHERE provider_attachment_id IS NOT NULL AND provider_attachment_id <> ''"
                " DO NOTHING",
                (
                    codec.new_id(), codec.to_id(user_id), codec.to_id(email_id), provider_id,
                    descriptor.get("filename") or descriptor.get("name") or "unnamed",
                    descriptor.get("mime_type") or descriptor.get("contentType") or "application/octet-stream",
                    descriptor.get("size_bytes") or descriptor.get("size") or 0,
                    tx.now_text,
                ),
            ).rowcount
    return created


__all__ = [
    "ensure_descriptors",
    "claim_email_attachment",
    "delete",
    "finish_email_attachment",
    "for_email",
    "get",
    "insert",
    "store_result",
]
