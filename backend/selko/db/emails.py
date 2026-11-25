"""Email work state: the claim, the fenced failure, reprocess, the atomic save.

Ports of the Postgres functions in docs/specs/sqlite-single-process/
02-data-layer.md §2.1 (1-6), plus the table reads and writes the email
services made through supabase-py and asyncpg (§3.7, §3.8, §4).

Postgres semantics kept on purpose:

- every timestamp the functions write is the transaction's ``tx.now``
  (Postgres ``now()`` is constant inside a function);
- ``ORDER BY date_sent ASC NULLS LAST`` is written ``date_sent IS NULL,
  date_sent`` because SQLite sorts NULLs first;
- ``IS DISTINCT FROM`` fences compare in Python with ``!=`` on values that may
  be ``None``, which is the same truth table;
- one expired ``processing`` lease is reclaimed per claim call, before the
  fresh claim, exactly as ``claim_unprocessed_email`` did.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from selko.db import codec
from selko.db.connection import Database, Tx
from selko.db.errors import EmailActivelyLeased, InvalidArgument, NotFound

# _email_is_claimable(e), as a SQL fragment over alias ``e``. ``:now`` is the
# transaction's timestamp. Shared with health_work_state's ready count so the
# two can never drift (Postgres duplicated it by hand).
CLAIMABLE_EMAIL_PREDICATE = """
    e.processing_status = 'pending'
    AND e.attempts < e.max_attempts
    AND (e.locked_until IS NULL OR e.locked_until < :now)
    AND (e.next_retry_at IS NULL OR e.next_retry_at <= :now)
    AND NOT EXISTS (
        SELECT 1 FROM attachments a
        WHERE a.email_id = e.id
          AND a.ingestion_status IN ('pending', 'processing', 'retry')
    )
"""

# The columns save_email_with_attachment_descriptors may set, from the
# Postgres function's whitelist. Identifiers in the generated SQL come only
# from here, never from the payload.
EMAIL_SAVE_COLUMNS: tuple[str, ...] = (
    "user_id", "email_provider", "provider_message_id", "thread_id",
    "subject", "from_email", "from_name", "to_emails", "date_sent",
    "snippet", "provider_labels", "has_attachments", "body_text",
    "is_calendar_invite", "integration_id", "provider_folder_ids",
    "content_hash",
)
_CONFLICT_COLUMNS = ("user_id", "email_provider", "provider_message_id")
_ARRAY_COLUMNS = frozenset({"to_emails", "provider_labels", "provider_folder_ids"})
_BOOL_COLUMNS = frozenset({"has_attachments", "is_calendar_invite"})
_TIMESTAMP_COLUMNS = frozenset({"date_sent"})
_ID_COLUMNS = frozenset({"user_id", "integration_id"})


def _decode(db: Database, row: Any) -> dict[str, Any] | None:
    return db.schema.decode("emails", row)


def _greatest(*values: int | None) -> int | None:
    """Postgres GREATEST: NULL arguments are ignored."""
    present = [v for v in values if v is not None]
    return max(present) if present else None


def _least(*values: int | None) -> int | None:
    """Postgres LEAST: NULL arguments are ignored."""
    present = [v for v in values if v is not None]
    return min(present) if present else None


def _left(value: str | None, n: int) -> str | None:
    return None if value is None else value[:n]


# ---------------------------------------------------------------------------
# 1 _email_is_claimable
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 2 claim_unprocessed_email
# ---------------------------------------------------------------------------


def _reclaim_one_expired(tx: Tx) -> None:
    stale = tx.execute(
        "SELECT id, attempts, max_attempts FROM emails"
        " WHERE processing_status = 'processing'"
        "   AND locked_until IS NOT NULL AND locked_until < ?"
        " ORDER BY locked_until LIMIT 1",
        (tx.now_text,),
    ).fetchone()
    if stale is None:
        return
    if stale["attempts"] < stale["max_attempts"]:
        tx.execute(
            "UPDATE emails SET processing_status = 'pending', processing_error = NULL,"
            " locked_by = NULL, locked_until = NULL WHERE id = ?",
            (stale["id"],),
        )
    else:
        tx.execute(
            "UPDATE emails SET processing_status = 'failed',"
            " dead_letter_reason = 'lease_expired_at_limit', dead_letter_at = ?,"
            " locked_by = NULL, locked_until = NULL WHERE id = ?",
            (tx.now_text, stale["id"]),
        )


def claim_unprocessed_email(
    db: Database, worker_id: str, lock_duration_seconds: int = 300
) -> dict[str, Any] | None:
    """Reclaim one expired lease, then claim the oldest claimable email.

    Returns the claimed row (after the claim's update) or ``None``.
    """
    with db.write() as tx:
        _reclaim_one_expired(tx)
        lease = _greatest(lock_duration_seconds, 1)
        row = tx.execute(
            "UPDATE emails SET processing_status = 'processing', processing_error = NULL,"
            " locked_by = :worker, locked_until = :until,"
            " attempts = attempts + 1, lock_generation = lock_generation + 1"
            " WHERE id = (SELECT e.id FROM emails e WHERE"
            f" {CLAIMABLE_EMAIL_PREDICATE}"
            "   ORDER BY e.date_sent IS NULL, e.date_sent, e.created_at LIMIT 1)"
            " RETURNING *",
            {"worker": worker_id, "until": tx.ts(lease), "now": tx.now_text},
        ).fetchone()
        claimed = dict(row) if row is not None else None
    return _decode(db, claimed)


# ---------------------------------------------------------------------------
# 3 fail_email_processing
# ---------------------------------------------------------------------------


def fail_email_processing(
    db: Database,
    email_id: str,
    worker_id: str,
    generation: int,
    error_code: str | None,
    error_detail: str | None,
    retry_base_seconds: int | None,
    retry_max_seconds: int | None,
) -> dict[str, Any]:
    """The fenced retry-or-terminate transition.

    ``error_detail`` is accepted and, as in Postgres, not stored. Returns
    ``{fenced, status}`` for a stale caller, else ``{fenced, status,
    attempts[, next_retry_at]}``.
    """
    email_id = codec.to_id(email_id)  # type: ignore[assignment]
    with db.write() as tx:
        email = tx.execute(
            "SELECT locked_by, lock_generation, attempts, max_attempts, processing_status"
            " FROM emails WHERE id = ?",
            (email_id,),
        ).fetchone()
        if email is None:
            raise NotFound(f"email {email_id} not found")

        if email["locked_by"] != worker_id or email["lock_generation"] != generation:
            return {"fenced": True, "status": email["processing_status"]}

        code = _left(error_code, 100)
        attempts = email["attempts"]
        if attempts < email["max_attempts"]:
            exponent = _least(_greatest(attempts - 1, 0), 5)
            delay = _least(
                _greatest(retry_max_seconds, 1),
                _greatest(retry_base_seconds, 1) * 2 ** exponent,  # type: ignore[operator]
            )
            next_retry_at = tx.ts(delay)  # type: ignore[arg-type]
            tx.execute(
                "UPDATE emails SET processing_status = 'pending', processing_error = ?,"
                " locked_by = NULL, locked_until = NULL, next_retry_at = ? WHERE id = ?",
                (code, next_retry_at, email_id),
            )
            return {"fenced": False, "status": "pending", "attempts": attempts,
                    "next_retry_at": next_retry_at}

        tx.execute(
            "UPDATE emails SET processing_status = 'failed', processing_error = ?,"
            " dead_letter_reason = ?, dead_letter_at = ?,"
            " locked_by = NULL, locked_until = NULL WHERE id = ?",
            (code, code, tx.now_text, email_id),
        )
        return {"fenced": False, "status": "failed", "attempts": attempts}


# ---------------------------------------------------------------------------
# 4 reprocess_email
# ---------------------------------------------------------------------------


def reprocess_email(db: Database, user_id: str, email_id: str) -> dict[str, Any] | None:
    """Reset the user's email to a fresh pending row.

    ``None`` when the email does not exist or is not the user's (Postgres
    returned no rows); `EmailActivelyLeased` while a worker holds a live lease.
    A malformed id matches no row.
    """
    try:
        codec.to_id(email_id)
    except (ValueError, TypeError, AttributeError):
        return None
    with db.write() as tx:
        email = tx.execute(
            "SELECT processing_status, locked_until FROM emails WHERE id = ? AND user_id = ?",
            (codec.to_id(email_id), codec.to_id(user_id)),
        ).fetchone()
        if email is None:
            return None
        if (
            email["processing_status"] == "processing"
            and email["locked_until"] is not None
            and email["locked_until"] > tx.now_text
        ):
            raise EmailActivelyLeased("email_actively_leased")
        row = tx.execute(
            "UPDATE emails SET processing_status = 'pending', processing_error = NULL,"
            " processing_outcome = NULL, processing_explanation = NULL,"
            " processing_result = NULL, processed_at = NULL,"
            " locked_by = NULL, locked_until = NULL, next_retry_at = NULL,"
            " dead_letter_reason = NULL, dead_letter_at = NULL,"
            " attempts = 0, lock_generation = lock_generation + 1"
            " WHERE id = ? RETURNING *",
            (codec.to_id(email_id),),
        ).fetchone()
        updated = dict(row)
    return _decode(db, updated)


# ---------------------------------------------------------------------------
# 5 unlock_expired_email_locks
# ---------------------------------------------------------------------------


def unlock_expired_email_locks(db: Database) -> int:
    """Expired leases back to pending, or failed at the attempt limit.

    Returns the number returned to pending (Postgres counted only those).
    """
    with db.write() as tx:
        return _unlock_emails(tx, expired_only=True)[0]


def _unlock_emails(tx: Tx, *, expired_only: bool) -> tuple[int, int]:
    """(returned to pending, failed at the limit). Shared with the startup reset."""
    lease = " AND locked_until < :now" if expired_only else ""
    retried = tx.execute(
        "UPDATE emails SET processing_status = 'pending', processing_error = NULL,"
        " locked_by = NULL, locked_until = NULL"
        f" WHERE processing_status = 'processing'{lease} AND attempts < max_attempts",
        {"now": tx.now_text},
    ).rowcount
    failed = tx.execute(
        "UPDATE emails SET processing_status = 'failed',"
        " dead_letter_reason = 'lease_expired_at_limit', dead_letter_at = :now,"
        " locked_by = NULL, locked_until = NULL"
        f" WHERE processing_status = 'processing'{lease} AND attempts >= max_attempts",
        {"now": tx.now_text},
    ).rowcount
    return retried, failed


# ---------------------------------------------------------------------------
# 6 save_email_with_attachment_descriptors
# ---------------------------------------------------------------------------

_BIGINT = re.compile(r"^\s*[+-]?\d+\s*$")


def _json_text(value: Any) -> str | None:
    """What Postgres ``jsonb ->> key`` gives for a JSON value."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return codec.to_json(value)


def _nullif_empty(value: str | None) -> str | None:
    return None if value == "" else value


def _to_bigint(value: str | None, field: str) -> int | None:
    if value is None:
        return None
    if not _BIGINT.match(value):
        raise InvalidArgument(f"invalid input syntax for type bigint: {value!r} ({field})")
    return int(value)


def _to_timestamp(value: Any, field: str) -> str | None:
    """Postgres ``::timestamptz``: an offset is honoured, a naive time is UTC."""
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            moment = value
        else:
            text = str(value).strip()
            moment = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
    except ValueError as exc:
        raise InvalidArgument(f"invalid timestamp for {field}: {value!r}") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return codec.to_timestamp(moment)


def _to_bool(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int) and value in (0, 1):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"t", "true", "y", "yes", "on", "1"}:
            return 1
        if lowered in {"f", "false", "n", "no", "off", "0"}:
            return 0
    raise InvalidArgument(f"invalid input syntax for type boolean: {value!r} ({field})")


def _coerce_email_value(column: str, value: Any) -> Any:
    """What jsonb_populate_record did implicitly, done explicitly."""
    if value is None:
        return None
    if column in _ARRAY_COLUMNS:
        if not isinstance(value, (list, tuple)):
            raise InvalidArgument(f"{column} must be an array")
        return codec.to_json([_json_text(v) for v in value])
    if column in _BOOL_COLUMNS:
        return _to_bool(value, column)
    if column in _TIMESTAMP_COLUMNS:
        return _to_timestamp(value, column)
    if column in _ID_COLUMNS:
        try:
            return codec.to_id(value)
        except ValueError as exc:
            raise InvalidArgument(f"invalid uuid for {column}: {value!r}") from exc
    return _json_text(value)


def save_email_with_attachment_descriptors(
    db: Database,
    user_id: str,
    email: Mapping[str, Any],
    descriptors: Iterable[Mapping[str, Any]] | None,
    calendar_components: Iterable[Mapping[str, Any]] | None = (),
) -> str:
    """Upsert the email (only the supplied columns), its attachment
    descriptors and its calendar components in one transaction.

    The readiness gate (`CLAIMABLE_EMAIL_PREDICATE`) can therefore never see an
    email whose descriptors are not written yet. An empty component list
    leaves earlier components in place. Returns the email id.
    """
    payload = dict(email)
    payload["user_id"] = user_id
    if not all(k in payload for k in _CONFLICT_COLUMNS):
        raise InvalidArgument("p_email must include user_id, email_provider and provider_message_id")
    columns = [c for c in EMAIL_SAVE_COLUMNS if c in payload]
    set_columns = [c for c in columns if c not in _CONFLICT_COLUMNS]
    if not set_columns:
        raise InvalidArgument(
            "save_email_with_attachment_descriptors: no settable columns resolved from p_email"
        )
    values = {c: _coerce_email_value(c, payload[c]) for c in columns}
    uid = values["user_id"]

    if descriptors is None:
        descriptors = []
    attachment_rows = []
    for d in descriptors:
        if not isinstance(d, Mapping):
            continue  # ``d->>'x'`` on a non-object is NULL: filtered out
        provider_attachment_id = _json_text(d.get("provider_attachment_id"))
        if provider_attachment_id is None or provider_attachment_id == "":
            continue
        filename = (_nullif_empty(_json_text(d.get("filename")))
                    or _nullif_empty(_json_text(d.get("name"))) or "unnamed")
        mime_type = (_nullif_empty(_json_text(d.get("mime_type")))
                     or _nullif_empty(_json_text(d.get("contentType")))
                     or "application/octet-stream")
        size = _to_bigint(_nullif_empty(_json_text(d.get("size_bytes"))), "size_bytes")
        if size is None:
            size = _to_bigint(_nullif_empty(_json_text(d.get("size"))), "size")
        attachment_rows.append((provider_attachment_id, filename, mime_type, 0 if size is None else size))

    if calendar_components is None:
        calendar_components = []
    if isinstance(calendar_components, (str, bytes, Mapping)):
        raise InvalidArgument("p_calendar_components must be an array")
    components = list(calendar_components)

    with db.write() as tx:
        insert_columns = ["id", "created_at", *columns]
        params = [codec.new_id(), tx.now_text, *(values[c] for c in columns)]
        row = tx.execute(
            f"INSERT INTO emails ({', '.join(insert_columns)})"
            f" VALUES ({', '.join('?' for _ in insert_columns)})"
            " ON CONFLICT (user_id, email_provider, provider_message_id) DO UPDATE SET "
            + ", ".join(f"{c} = excluded.{c}" for c in set_columns)
            + " RETURNING id",
            params,
        ).fetchone()
        email_id = row["id"]

        for provider_attachment_id, filename, mime_type, size in attachment_rows:
            tx.execute(
                "INSERT INTO attachments (id, user_id, email_id, provider_attachment_id, filename,"
                " mime_type, size_bytes, ingestion_status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)"
                " ON CONFLICT (email_id, provider_attachment_id)"
                " WHERE provider_attachment_id IS NOT NULL AND provider_attachment_id <> ''"
                " DO NOTHING",
                (codec.new_id(), uid, email_id, provider_attachment_id, filename, mime_type,
                 size, tx.now_text),
            )

        if components:
            tx.execute("DELETE FROM email_calendar_components WHERE email_id = ?", (email_id,))
            for index, c in enumerate(components):
                if not isinstance(c, Mapping):
                    c = {}
                sequence = _to_bigint(_nullif_empty(_json_text(c.get("sequence"))), "sequence")
                tx.execute(
                    "INSERT INTO email_calendar_components (id, email_id, user_id, component_index,"
                    " method, uid_hash, recurrence_id, recurrence_range, sequence, dtstamp,"
                    " component_status, start_datetime, end_datetime, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        codec.new_id(), email_id, uid, index,
                        _json_text(c.get("method")), _json_text(c.get("uid_hash")),
                        _json_text(c.get("recurrence_id")), _json_text(c.get("recurrence_range")),
                        0 if sequence is None else sequence,
                        _to_timestamp(_nullif_empty(_json_text(c.get("dtstamp"))), "dtstamp"),
                        _json_text(c.get("component_status")),
                        _to_timestamp(_nullif_empty(_json_text(c.get("start_datetime"))), "start_datetime"),
                        _to_timestamp(_nullif_empty(_json_text(c.get("end_datetime"))), "end_datetime"),
                        tx.now_text,
                    ),
                )
    return email_id


# ---------------------------------------------------------------------------
# Table reads and writes the services made directly (§3.7, §3.8, §4)
# ---------------------------------------------------------------------------


def complete_email_processing(db: Database, email_id: str) -> bool:
    """``services/emails.complete_email_processing``'s inline UPDATE (unfenced, as today)."""
    with db.write() as tx:
        return tx.execute(
            "UPDATE emails SET processing_status = 'processed', processing_error = NULL,"
            " processed_at = ?, locked_by = NULL, locked_until = NULL WHERE id = ?",
            (tx.now_text, codec.to_id(email_id)),
        ).rowcount > 0


def get_email(db: Database, user_id: str, email_id: str) -> dict[str, Any] | None:
    """One of the user's emails, or ``None``."""
    row = db.query_one(
        "SELECT * FROM emails WHERE id = ? AND user_id = ?",
        (codec.to_id(email_id), codec.to_id(user_id)),
    )
    return _decode(db, row)


def get_for_extraction(db: Database, email_id: str) -> dict[str, Any] | None:
    """The full email row for the extraction worker (worker-scoped), or ``None``.

    Replaces ``event_processing.fetch_email_with_attachments``'s
    ``select * eq id single``.
    """
    return _decode(db, db.query_one("SELECT * FROM emails WHERE id = ?", (codec.to_id(email_id),)))


def acquisition_context(db: Database, email_id: str) -> dict[str, Any] | None:
    """``{user_id, email_provider, provider_message_id, integration_id}`` of an email.

    Worker-scoped: the attachment worker reaches the email through a claimed
    attachment row (``workers/email_ingestion.acquire_attachment``).
    """
    row = db.query_one(
        "SELECT user_id, email_provider, provider_message_id, integration_id FROM emails WHERE id = ?",
        (codec.to_id(email_id),),
    )
    return None if row is None else dict(row)


def exists_owned(db: Database, user_id: str, email_id: str) -> bool:
    """Whether the email exists and is the user's (a malformed id exists for no one)."""
    try:
        codec.to_id(email_id)
    except (ValueError, TypeError, AttributeError):
        return False
    return db.query_one(
        "SELECT 1 FROM emails WHERE id = ? AND user_id = ?",
        (codec.to_id(email_id), codec.to_id(user_id)),
    ) is not None


def list_ids_recent(db: Database, user_id: str, limit: int) -> list[str]:
    """The user's newest email ids by ``date_sent`` (PostgREST ``order desc``: NULLs first)."""
    rows = db.query(
        "SELECT id FROM emails WHERE user_id = ?"
        " ORDER BY date_sent IS NOT NULL, date_sent DESC, rowid DESC LIMIT ?",
        (codec.to_id(user_id), max(int(limit), 0)),
    )
    return [r["id"] for r in rows]


def active_mail_integrations(db: Database, user_id: str) -> list[dict[str, Any]]:
    """The user's active Gmail/Outlook integrations: ``[{id, provider}]``.

    ``fetch_emails_for_user``'s integrations select (§3.7; the spec names
    ``db.integrations`` as its eventual home).
    """
    rows = db.query(
        "SELECT id, provider FROM integrations"
        " WHERE user_id = ? AND provider IN ('gmail', 'outlook') AND status = 'active'"
        " ORDER BY created_at, id",
        (codec.to_id(user_id),),
    )
    return [dict(r) for r in rows]


def request_poll(db: Database, integration_id: str) -> bool:
    """Bring the integration's next poll forward unless a run holds the lease.

    ``fetch_emails_for_user``'s email_sync_state update (§3.7; the spec names
    ``db.email_sync`` as its eventual home). True when a row was changed.
    """
    with db.write() as tx:
        return tx.execute(
            "UPDATE email_sync_state SET next_poll_at = ? WHERE integration_id = ? AND lease_owner IS NULL",
            (tx.now_text, codec.to_id(integration_id)),
        ).rowcount > 0


def email_is_claimable(db: Database, email_id: str) -> bool:
    """Whether the worker claim would consider this email right now."""
    row = db.query_one(
        f"SELECT 1 FROM emails e WHERE e.id = :id AND {CLAIMABLE_EMAIL_PREDICATE}",
        {"id": codec.to_id(email_id), "now": codec.now_text()},
    )
    return row is not None


__all__ = [
    "email_is_claimable",
    "CLAIMABLE_EMAIL_PREDICATE",
    "EMAIL_SAVE_COLUMNS",
    "acquisition_context",
    "active_mail_integrations",
    "claim_unprocessed_email",
    "complete_email_processing",
    "exists_owned",
    "fail_email_processing",
    "get_email",
    "get_for_extraction",
    "list_ids_recent",
    "reprocess_email",
    "request_poll",
    "save_email_with_attachment_descriptors",
    "unlock_expired_email_locks",
]
