"""Provider discovery, sync leases, ingestion items and folders.

Ports of the Postgres functions in docs/specs/sqlite-single-process/02-data-layer.md
§2.2 (8-18) and §2.11 (59), plus every table query the email-sync services
and workers make today (§3.5, §3.6, the email-sync parts of §3.10/§3.13, and
the email-sync asyncpg sites in §4).

Postgres semantics kept on purpose:

- ``now()`` is the transaction's ``tx.now``: a claim's returned
  ``lease_expires_at`` equals the stored one.
- ``FOR UPDATE SKIP LOCKED`` is unnecessary: ``db.write()`` holds the only
  write lock, so two claims can never take the same row.
- Leases are fenced exactly as the plpgsql bodies fenced them (owner and,
  where Postgres checked it, generation and expiry); a stale caller gets
  ``False`` and changes nothing.
- ``NULLS FIRST``/``LAST`` are written out, so ordering never depends on
  SQLite's default.
- Backoff uses Postgres' arithmetic: ``power(2, n)::integer`` rounds half to
  even, which Python's ``round`` also does.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from selko.db import codec, errors
from selko.db.connection import Database, Tx

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _id(value: Any) -> str | None:
    """A uuid argument as canonical text; Postgres refused malformed uuids (22P02)."""
    try:
        return codec.to_id(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise errors.InvalidArgument(f"invalid input syntax for type uuid: {value!r}") from exc


def _left(value: str | None, n: int) -> str | None:
    """Postgres ``left(text, n)``: the first n characters, NULL stays NULL."""
    return None if value is None else str(value)[:n]


def _backoff(base: int, maximum: int, exponent: int) -> int:
    """``LEAST(max, GREATEST(base, 1) * power(2, LEAST(exponent, 5))::integer)``."""
    return min(maximum, max(base, 1) * round(2.0 ** min(exponent, 5)))


def _json_text(value: Any) -> str | None:
    """What jsonb ``->>`` / ``jsonb_array_elements_text`` yields for a JSON value."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value, separators=(", ", ": "))


def _encode(db: Database, table: str, values: dict[str, Any]) -> dict[str, Any]:
    """Bindable values; ``*_at`` strings (ISO from the services) become stored text."""
    out = db.schema.encode(table, values)
    for column, value in out.items():
        if column.endswith("_at") and isinstance(value, str):
            out[column] = codec.to_timestamp(value)
    return out


def _decode(db: Database, table: str, row: Any) -> dict[str, Any] | None:
    return db.schema.decode(table, row)


def _lease_seconds(seconds: int) -> int:
    return max(int(seconds), 1)


# ---------------------------------------------------------------------------
# 8, 9: claims
# ---------------------------------------------------------------------------

_DUE_SYNC = """
SELECT s.* FROM email_sync_state s
JOIN integrations i ON i.id = s.integration_id
WHERE i.status = 'active' AND s.next_poll_at <= :now
  AND (s.lease_expires_at IS NULL OR s.lease_expires_at <= :now)
ORDER BY s.next_poll_at, s.last_success_at IS NOT NULL, s.last_success_at
LIMIT 1
"""

_DUE_RECONCILIATION = """
SELECT s.* FROM email_sync_state s
JOIN integrations i ON i.id = s.integration_id
WHERE i.status = 'active'
  AND (s.lease_expires_at IS NULL OR s.lease_expires_at <= :now)
  AND (s.last_reconciled_at IS NULL OR s.last_reconciled_at <= :day_ago)
  AND s.next_poll_at > :now
ORDER BY s.last_reconciled_at IS NOT NULL, s.last_reconciled_at, s.next_poll_at
LIMIT 1
"""


def _take_lease(tx: Tx, state: Any, worker_id: str, lease_seconds: int, kind: str) -> dict[str, Any]:
    integration_id = state["integration_id"]
    # Abandon first: email_sync_runs_one_running_per_integration is checked
    # per statement, so the insert below would otherwise violate it.
    tx.execute(
        "UPDATE email_sync_runs SET status = 'abandoned', completed_at = ?"
        " WHERE integration_id = ? AND status = 'running'",
        (tx.now_text, integration_id),
    )
    generation = int(state["lease_generation"]) + 1
    run_id = codec.new_id()
    tx.execute(
        "INSERT INTO email_sync_runs (id, integration_id, user_id, provider, run_kind, status,"
        " started_at, lease_generation) VALUES (?, ?, ?, ?, ?, 'running', ?, ?)",
        (run_id, integration_id, state["user_id"], state["provider"], kind, tx.now_text, generation),
    )
    expires = tx.ts(_lease_seconds(lease_seconds))
    tx.execute(
        "UPDATE email_sync_state SET lease_owner = ?, lease_generation = ?, lease_expires_at = ?,"
        " last_started_at = ?, updated_at = ? WHERE integration_id = ?",
        (worker_id, generation, expires, tx.now_text, tx.now_text, integration_id),
    )
    return {
        "integration_id": integration_id,
        "user_id": state["user_id"],
        "provider": state["provider"],
        "run_id": run_id,
        "run_kind": kind,
        "lease_generation": generation,
        "lease_expires_at": expires,
    }


def claim_due_email_sync(db: Database, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
    """Claim the most overdue active integration's poll; open its run (8)."""
    with db.write() as tx:
        state = tx.execute(_DUE_SYNC, {"now": tx.now_text}).fetchone()
        if state is None:
            return None
        kind = "initial" if state["last_success_at"] is None else "incremental"
        return _take_lease(tx, state, worker_id, lease_seconds, kind)


def claim_due_email_reconciliation(db: Database, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
    """Claim an idle integration whose reconciliation is a day old or never ran (9)."""
    with db.write() as tx:
        state = tx.execute(
            _DUE_RECONCILIATION, {"now": tx.now_text, "day_ago": tx.ts(-86400)}
        ).fetchone()
        if state is None:
            return None
        last = state["last_reconciled_at"]
        kind = "weekly_reconcile" if last is not None and last <= tx.ts(-7 * 86400) else "daily_reconcile"
        return _take_lease(tx, state, worker_id, lease_seconds, kind)


# ---------------------------------------------------------------------------
# 10-12: heartbeat, complete, fail
# ---------------------------------------------------------------------------


def heartbeat_email_sync(
    db: Database, integration_id: str, worker_id: str, generation: int, lease_seconds: int
) -> bool:
    """Extend a live lease; False if it is not this worker's generation or has expired (10)."""
    integration_id = _id(integration_id)
    with db.write() as tx:
        cur = tx.execute(
            "UPDATE email_sync_state SET lease_expires_at = ?, updated_at = ?"
            " WHERE integration_id = ? AND lease_owner = ? AND lease_generation = ?"
            " AND lease_expires_at > ?",
            (tx.ts(_lease_seconds(lease_seconds)), tx.now_text, integration_id, worker_id,
             generation, tx.now_text),
        )
        return cur.rowcount > 0


def complete_email_sync(
    db: Database,
    integration_id: str,
    run_id: str,
    worker_id: str,
    generation: int,
    poll_interval_seconds: int = 300,
    reconciled: bool = False,
) -> bool:
    """Release a live lease as a success and close its run (11)."""
    integration_id, run_id = _id(integration_id), _id(run_id)
    with db.write() as tx:
        now = tx.now_text
        cur = tx.execute(
            "UPDATE email_sync_state SET lease_owner = NULL, lease_expires_at = NULL,"
            " last_discovery_at = ?, last_success_at = ?,"
            " last_reconciled_at = CASE WHEN ? THEN ? ELSE last_reconciled_at END,"
            " consecutive_failures = 0, last_error_code = NULL, last_error_at = NULL,"
            " next_poll_at = ?, updated_at = ?"
            " WHERE integration_id = ? AND lease_owner = ? AND lease_generation = ?"
            " AND lease_expires_at > ?",
            (now, now, 1 if reconciled else 0, now, tx.ts(max(int(poll_interval_seconds), 1)), now,
             integration_id, worker_id, generation, now),
        )
        if cur.rowcount == 0:
            return False
        tx.execute(
            "UPDATE email_sync_runs SET status = 'completed', completed_at = ?"
            " WHERE id = ? AND integration_id = ? AND status = 'running' AND lease_generation = ?",
            (now, run_id, integration_id, generation),
        )
        return True


def fail_email_sync(
    db: Database,
    integration_id: str,
    run_id: str,
    worker_id: str,
    generation: int,
    error_code: str,
    error_detail: str | None = None,
    retry_base_seconds: int = 60,
    retry_max_seconds: int = 1800,
    auth_failure: bool = False,
) -> bool:
    """Release a lease as a failure with capped exponential backoff (12).

    As in Postgres, the fence is owner + generation only: a worker whose lease
    has expired but not been reclaimed may still record its failure.
    """
    integration_id, run_id = _id(integration_id), _id(run_id)
    with db.write() as tx:
        row = tx.execute(
            "SELECT consecutive_failures + 1 AS failures FROM email_sync_state"
            " WHERE integration_id = ? AND lease_owner = ? AND lease_generation = ?",
            (integration_id, worker_id, generation),
        ).fetchone()
        if row is None:
            return False
        failures = int(row["failures"])
        delay = _backoff(retry_base_seconds, retry_max_seconds, failures - 1)
        code = _left(error_code, 100)
        now = tx.now_text
        tx.execute(
            "UPDATE email_sync_runs SET status = 'failed', completed_at = ?, error_code = ?,"
            " error_detail = ? WHERE id = ? AND integration_id = ? AND status = 'running'"
            " AND lease_generation = ?",
            (now, code, _left(error_detail, 500), run_id, integration_id, generation),
        )
        tx.execute(
            "UPDATE email_sync_state SET lease_owner = NULL, lease_expires_at = NULL,"
            " consecutive_failures = ?, last_error_code = ?, last_error_at = ?, next_poll_at = ?,"
            " updated_at = ? WHERE integration_id = ? AND lease_owner = ? AND lease_generation = ?",
            (failures, code, now, tx.ts(delay), now, integration_id, worker_id, generation),
        )
        if auth_failure:
            tx.execute(
                "UPDATE integrations SET status = 'expired', updated_at = ? WHERE id = ?",
                (now, integration_id),
            )
        return True


# ---------------------------------------------------------------------------
# 13: discovery pages
# ---------------------------------------------------------------------------


def upsert_discovered_email_items(
    db: Database,
    integration_id: str,
    run_id: str,
    items: Iterable[dict[str, Any]] | None,
    cursor: str | None = None,
    folder_id: str | None = None,
) -> dict[str, int]:
    """Persist one provider page of message identities, then its cursor (13).

    Returns ``{"inserted_count", "existing_count", "provider_ids_seen"}``.
    """
    integration_id, run_id, folder_id = _id(integration_id), _id(run_id), _id(folder_id)
    page = list(items or [])
    with db.write() as tx:
        state = tx.execute(
            "SELECT user_id, provider FROM email_sync_state WHERE integration_id = ?",
            (integration_id,),
        ).fetchone()
        if state is None or state["user_id"] is None:
            raise errors.NotFound("Unknown email integration")
        seen = len(page)
        ids = [_json_text(item.get("provider_message_id")) for item in page]
        existing = tx.execute(
            "SELECT count(*) FROM email_ingestion_items WHERE integration_id = ?"
            " AND provider_message_id IN (SELECT value FROM json_each(?))",
            (integration_id, json.dumps([i for i in ids if i is not None])),
        ).fetchone()[0]

        rows: list[tuple[str, list[Any], str]] = []
        for item, message_id in zip(page, ids):
            if not message_id:  # NULLIF(..., '') IS NOT NULL
                continue
            folders_raw = item.get("provider_folder_ids")
            folders = [_json_text(f) for f in (folders_raw or [])]
            kind = _json_text(item.get("change_kind"))
            rows.append((message_id, folders, "upsert" if kind is None else kind))
        if len({r[0] for r in rows}) != len(rows):
            # One INSERT ... ON CONFLICT DO UPDATE in Postgres: a page naming
            # the same message twice failed as a whole (21000).
            raise errors.DbError("ON CONFLICT DO UPDATE command cannot affect row a second time")

        for message_id, folders, kind in rows:
            prior = tx.execute(
                "SELECT id, provider_folder_ids FROM email_ingestion_items"
                " WHERE integration_id = ? AND provider_message_id = ?",
                (integration_id, message_id),
            ).fetchone()
            if prior is None:
                tx.execute(
                    "INSERT INTO email_ingestion_items (id, integration_id, user_id, provider,"
                    " provider_message_id, provider_folder_ids, change_kind, first_discovered_at,"
                    " last_discovered_at, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (codec.new_id(), integration_id, state["user_id"], state["provider"], message_id,
                     json.dumps(folders), kind, tx.now_text, tx.now_text, tx.now_text, tx.now_text),
                )
                continue
            union = list(dict.fromkeys([*json.loads(prior["provider_folder_ids"] or "[]"), *folders]))
            tx.execute(
                "UPDATE email_ingestion_items SET provider_folder_ids = ?,"
                " change_kind = CASE WHEN acquisition_status = 'completed' THEN change_kind ELSE ? END,"
                " last_discovered_at = ?,"
                " acquisition_status = CASE WHEN acquisition_status IN ('retry', 'pending')"
                "   THEN 'pending' ELSE acquisition_status END,"
                " updated_at = ? WHERE id = ?",
                (json.dumps(union), kind, tx.now_text, tx.now_text, prior["id"]),
            )

        inserted = max(seen - existing, 0)
        already = min(seen, existing)
        tx.execute(
            "UPDATE email_sync_runs SET provider_ids_seen = provider_ids_seen + ?,"
            " ingestion_items_inserted = ingestion_items_inserted + ?,"
            " ingestion_items_existing = ingestion_items_existing + ?"
            " WHERE id = ? AND status = 'running'",
            (seen, inserted, already, run_id),
        )
        if folder_id is None and cursor is not None:
            tx.execute(
                "UPDATE integrations SET sync_cursor = ?, last_sync_at = ?, updated_at = ? WHERE id = ?",
                (cursor, tx.now_text, tx.now_text, integration_id),
            )
        elif folder_id is not None and cursor is not None:
            tx.execute(
                "UPDATE email_folders SET sync_cursor = ?, updated_at = ? WHERE id = ? AND integration_id = ?",
                (cursor, tx.now_text, folder_id, integration_id),
            )
        return {"inserted_count": inserted, "existing_count": already, "provider_ids_seen": seen}


def known_provider_message_ids(
    db: Database, integration_id: str, provider_message_ids: Iterable[str], chunk: int = 1000
) -> set[str]:
    """The subset of ``provider_message_ids`` already discovered for the integration."""
    integration_id = _id(integration_id)
    ids = [str(pid) for pid in provider_message_ids if pid]
    known: set[str] = set()
    for start in range(0, len(ids), max(chunk, 1)):
        rows = db.query(
            "SELECT provider_message_id FROM email_ingestion_items WHERE integration_id = ?"
            " AND provider_message_id IN (SELECT value FROM json_each(?))",
            (integration_id, json.dumps(ids[start : start + chunk])),
        )
        known.update(r["provider_message_id"] for r in rows if r["provider_message_id"])
    return known


# ---------------------------------------------------------------------------
# 14-16: ingestion items
# ---------------------------------------------------------------------------


def claim_email_ingestion_item(db: Database, worker_id: str, lease_seconds: int = 900) -> dict[str, Any] | None:
    """Lease the oldest claimable ingestion item (14)."""
    with db.write() as tx:
        row = tx.execute(
            "UPDATE email_ingestion_items SET acquisition_status = 'processing', attempts = attempts + 1,"
            " lease_owner = :worker, lease_expires_at = :until, updated_at = :now"
            " WHERE id = (SELECT id FROM email_ingestion_items"
            "   WHERE acquisition_status IN ('pending', 'retry', 'processing') AND attempts < max_attempts"
            "     AND (next_retry_at IS NULL OR next_retry_at <= :now)"
            "     AND (lease_expires_at IS NULL OR lease_expires_at <= :now)"
            "   ORDER BY created_at LIMIT 1)"
            " RETURNING *",
            {"worker": worker_id, "until": tx.ts(_lease_seconds(lease_seconds)), "now": tx.now_text},
        ).fetchone()
        return _decode(db, "email_ingestion_items", row)


def complete_email_ingestion_item(db: Database, item_id: str, worker_id: str, email_id: str) -> bool:
    """Mark a leased item acquired (15)."""
    item_id, email_id = _id(item_id), _id(email_id)
    with db.write() as tx:
        cur = tx.execute(
            "UPDATE email_ingestion_items SET acquisition_status = 'completed', email_id = ?,"
            " completed_at = ?, lease_owner = NULL, lease_expires_at = NULL, last_error_code = NULL,"
            " updated_at = ? WHERE id = ? AND acquisition_status = 'processing' AND lease_owner = ?",
            (email_id, tx.now_text, tx.now_text, item_id, worker_id),
        )
        return cur.rowcount > 0


def fail_email_ingestion_item(
    db: Database,
    item_id: str,
    worker_id: str,
    error_code: str,
    retry_base_seconds: int = 60,
    retry_max_seconds: int = 1800,
    terminal: bool = False,
) -> bool:
    """Record an acquisition failure: retry with backoff, or dead-letter (16)."""
    item_id = _id(item_id)
    with db.write() as tx:
        row = tx.execute(
            "SELECT attempts, max_attempts FROM email_ingestion_items WHERE id = ? AND lease_owner = ?",
            (item_id, worker_id),
        ).fetchone()
        if row is None:
            return False
        retry = not terminal and row["attempts"] < row["max_attempts"]
        delay = _backoff(retry_base_seconds, retry_max_seconds, int(row["attempts"]) - 1)
        cur = tx.execute(
            "UPDATE email_ingestion_items SET acquisition_status = ?, next_retry_at = ?,"
            " last_error_code = ?, last_error_at = ?, lease_owner = NULL, lease_expires_at = NULL,"
            " updated_at = ? WHERE id = ? AND lease_owner = ?",
            ("retry" if retry else "dead_letter", tx.ts(delay) if retry else None,
             _left(error_code, 100), tx.now_text, tx.now_text, item_id, worker_id),
        )
        return cur.rowcount > 0


def remove_ingestion_item(db: Database, item_id: str, worker_id: str) -> bool:
    """The provider no longer has the message: close the leased item as removed."""
    item_id = _id(item_id)
    with db.write() as tx:
        row = tx.execute(
            "UPDATE email_ingestion_items SET acquisition_status = 'removed', lease_owner = NULL,"
            " lease_expires_at = NULL, completed_at = ?, updated_at = ?"
            " WHERE id = ? AND lease_owner = ? RETURNING id",
            (tx.now_text, tx.now_text, item_id, worker_id),
        ).fetchone()
        return row is not None


def dead_letter_item_integration_ids(db: Database) -> set[str]:
    """Integrations owning at least one dead-lettered ingestion item."""
    rows = db.query(
        "SELECT DISTINCT integration_id FROM email_ingestion_items WHERE acquisition_status = 'dead_letter'"
    )
    return {r["integration_id"] for r in rows if r["integration_id"]}


def dead_letter_attachment_integration_ids(db: Database) -> set[str]:
    """Integrations owning at least one dead-lettered attachment (via its email)."""
    rows = db.query(
        "SELECT DISTINCT e.integration_id FROM attachments a JOIN emails e ON e.id = a.email_id"
        " WHERE a.ingestion_status = 'dead_letter'"
    )
    return {r["integration_id"] for r in rows if r["integration_id"]}


# ---------------------------------------------------------------------------
# 17: prompt poll; sync state reads/writes
# ---------------------------------------------------------------------------


def request_email_sync_now(db: Database, user_id: str | None, integration_id: str) -> bool:
    """Make the caller's integration due now, unless a worker holds its lease (17)."""
    integration_id = _id(integration_id)
    user_id = _id(user_id)
    with db.write() as tx:
        owned = tx.execute(
            "SELECT 1 FROM integrations WHERE id = ? AND user_id = ?", (integration_id, user_id)
        ).fetchone()
        if owned is None:
            return False
        cur = tx.execute(
            "UPDATE email_sync_state SET next_poll_at = ?, updated_at = ?"
            " WHERE integration_id = ? AND (lease_expires_at IS NULL OR lease_expires_at <= ?)",
            (tx.now_text, tx.now_text, integration_id, tx.now_text),
        )
        return cur.rowcount > 0


def all_states(db: Database) -> list[dict[str, Any]]:
    """Every sync state row (the health evaluator's scan)."""
    rows = db.query("SELECT * FROM email_sync_state ORDER BY rowid")
    return [_decode(db, "email_sync_state", r) for r in rows]  # type: ignore[misc]


def folders_refreshed_at(db: Database, integration_id: str) -> str | None:
    row = db.query_one(
        "SELECT folders_refreshed_at FROM email_sync_state WHERE integration_id = ?", (_id(integration_id),)
    )
    return None if row is None else row["folders_refreshed_at"]


def mark_folders_refreshed(db: Database, integration_id: str) -> bool:
    """Stamp the hourly folder refresh (the PostgREST update set only this column)."""
    with db.write() as tx:
        cur = tx.execute(
            "UPDATE email_sync_state SET folders_refreshed_at = ? WHERE integration_id = ?",
            (tx.now_text, _id(integration_id)),
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Folders (§2.11 59, §3.5, §3.13, routes/integrations.py)
# ---------------------------------------------------------------------------


def folders_for_integration(db: Database, integration_id: str, provider: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM email_folders WHERE integration_id = ?"
    params: list[Any] = [_id(integration_id)]
    if provider is not None:
        sql += " AND provider = ?"
        params.append(provider)
    rows = db.query(sql + " ORDER BY rowid", params)
    return [_decode(db, "email_folders", r) for r in rows]  # type: ignore[misc]


def folder_ids(db: Database, integration_id: str, provider: str, is_included: bool) -> list[str]:
    """``provider_folder_id`` of the integration's folders with this inclusion."""
    rows = db.query(
        "SELECT provider_folder_id FROM email_folders WHERE integration_id = ? AND provider = ?"
        " AND is_included = ? ORDER BY rowid",
        (_id(integration_id), provider, 1 if is_included else 0),
    )
    return [r["provider_folder_id"] for r in rows]


def upsert_folders(db: Database, integration_id: str, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """PostgREST ``upsert(rows, on_conflict='integration_id,provider_folder_id')``.

    Columns are the union of the rows' keys; a key missing from one row binds
    NULL (supabase-py's ``default_to_null``). New rows get an id and
    ``discovered_at``; existing rows keep both.
    """
    integration_id = _id(integration_id)
    batch = [dict(r) for r in rows]
    if not batch:
        return []
    for row in batch:
        row.setdefault("integration_id", integration_id)
        if _id(row["integration_id"]) != integration_id:
            raise errors.InvalidArgument("folder row belongs to another integration")
    keys = list(dict.fromkeys(k for row in batch for k in row))
    if len({row.get("provider_folder_id") for row in batch}) != len(batch):
        raise errors.DbError("ON CONFLICT DO UPDATE command cannot affect row a second time")
    update_cols = [k for k in keys if k not in ("integration_id", "provider_folder_id", "id")]
    out: list[dict[str, Any]] = []
    with db.write() as tx:
        for row in batch:
            values = _encode(db, "email_folders", {k: row.get(k) for k in keys})
            insert = {"id": codec.new_id(), "discovered_at": tx.now_text, "updated_at": tx.now_text}
            insert.update({k: v for k, v in values.items()})
            cols = list(insert)
            set_clause = ", ".join(f"{c} = excluded.{c}" for c in update_cols) or "provider_folder_id = excluded.provider_folder_id"
            found = tx.execute(
                f"INSERT INTO email_folders ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
                f" ON CONFLICT (integration_id, provider_folder_id) DO UPDATE SET {set_clause} RETURNING *",
                tuple(insert[c] for c in cols),
            ).fetchone()
            out.append(_decode(db, "email_folders", found))  # type: ignore[arg-type]
    return out


def delete_folder(db: Database, integration_id: str, folder_id: str) -> bool:
    """Forget a folder the provider no longer has (Graph 404)."""
    with db.write() as tx:
        cur = tx.execute(
            "DELETE FROM email_folders WHERE id = ? AND integration_id = ?",
            (_id(folder_id), _id(integration_id)),
        )
        return cur.rowcount > 0


def list_user_folders(db: Database, user_id: str, provider: str) -> list[dict[str, Any]]:
    """Settings' folder list: the user's non-system folders, by path."""
    rows = db.query(
        "SELECT * FROM email_folders WHERE user_id = ? AND provider = ? AND is_system = 0"
        " ORDER BY full_path",
        (_id(user_id), provider),
    )
    return [_decode(db, "email_folders", r) for r in rows]  # type: ignore[misc]


def get_user_folder(db: Database, user_id: str, folder_id: str, provider: str) -> dict[str, Any] | None:
    row = db.query_one(
        "SELECT * FROM email_folders WHERE id = ? AND user_id = ? AND provider = ? AND is_system = 0",
        (_id(folder_id), _id(user_id), provider),
    )
    return _decode(db, "email_folders", row)


def set_email_folder_preference(
    db: Database, user_id: str | None, folder_id: str, is_included: bool
) -> dict[str, Any] | None:
    """The only writer of ``is_included``: a durable user override (59)."""
    if user_id is None:
        raise errors.InvalidArgument("Authentication required")
    with db.write() as tx:
        row = tx.execute(
            "UPDATE email_folders SET is_included = ?, user_override = 1, sync_cursor = NULL,"
            " updated_at = ? WHERE id = ? AND user_id = ? AND is_system = 0"
            " AND is_permanently_excluded = 0 AND provider IN ('gmail', 'outlook') RETURNING *",
            (1 if is_included else 0, tx.now_text, _id(folder_id), _id(user_id)),
        ).fetchone()
        return _decode(db, "email_folders", row)


# ---------------------------------------------------------------------------
# Integration reads the ingestion workers make (§3.6, §3.13)
#
# Operational incidents and the Graph failure ledger live in selko.db.ops.
# ---------------------------------------------------------------------------


def integration_statuses(db: Database) -> dict[str, str]:
    """``{integration_id: status}`` for every integration (the health evaluator's scan)."""
    rows = db.query("SELECT id, status FROM integrations ORDER BY rowid")
    return {r["id"]: r["status"] for r in rows}


def get_integration_by_id(db: Database, integration_id: str) -> dict[str, Any] | None:
    """One integration row by id (worker-scoped: the claim already names its owner)."""
    row = db.query_one("SELECT * FROM integrations WHERE id = ?", (_id(integration_id),))
    return _decode(db, "integrations", row)


def active_calendar_integrations(db: Database) -> list[dict[str, Any]]:
    """``[{id, user_id, provider, scopes}]`` of every active Google/Outlook integration."""
    rows = db.query(
        "SELECT id, user_id, provider, scopes FROM integrations"
        " WHERE status = 'active' AND provider IN ('google_calendar', 'outlook')"
        " ORDER BY created_at, rowid"
    )
    return [_decode(db, "integrations", r) for r in rows]  # type: ignore[misc]


def get_sync_state(db: Database, integration_id: str) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM email_sync_state WHERE integration_id = ?", (_id(integration_id),))
    return _decode(db, "email_sync_state", row)


__all__ = [
    "get_sync_state",
    "active_calendar_integrations",
    "all_states",
    "claim_due_email_reconciliation",
    "claim_due_email_sync",
    "claim_email_ingestion_item",
    "complete_email_ingestion_item",
    "complete_email_sync",
    "dead_letter_attachment_integration_ids",
    "dead_letter_item_integration_ids",
    "delete_folder",
    "fail_email_ingestion_item",
    "fail_email_sync",
    "folder_ids",
    "folders_for_integration",
    "folders_refreshed_at",
    "get_integration_by_id",
    "get_user_folder",
    "heartbeat_email_sync",
    "integration_statuses",
    "known_provider_message_ids",
    "list_user_folders",
    "mark_folders_refreshed",
    "remove_ingestion_item",
    "request_email_sync_now",
    "set_email_folder_preference",
    "upsert_discovered_email_items",
    "upsert_folders",
]
