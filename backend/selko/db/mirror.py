"""The calendar mirror: ``calendar_entries``, ``calendar_mirror_state`` and
the identity hints indexed against mirrored entries.

The SQLite replacement for the supabase-py calls in
``services/calendar_mirror.py`` (docs/specs/sqlite-single-process/
02-data-layer.md §3.3). The hints that ``commit_email_extraction`` writes
against Selko's own events belong to ``db/events.py``; this module writes
only hints whose ``calendar_entry_id`` is set.

===========================================  ==================================
Service call site                            db function
===========================================  ==================================
services/calendar_mirror.py:188              get_state
  (sync_calendar: sync_token)
services/calendar_mirror.py:238              upsert_entries
  (sync_calendar: entries upsert)
services/calendar_mirror.py:263              save_state
  (sync_calendar: state upsert)
services/calendar_mirror.py:330              upsert_entry_hints
  (_write_entry_hints)
services/calendar_mirror.py:356              entries_by_provider_ids
  (_reload_stored)
services/calendar_mirror.py:379              indexable_entries
  (_index_unhinted_entries: entries)
services/calendar_mirror.py:399              hinted_entry_ids
  (_index_unhinted_entries: hinted ids)
===========================================  ==================================

``upsert_entries`` also returns the stored rows (``RETURNING``), which is what
``_reload_stored`` exists to fetch because PostgREST echoed nothing; the
integrator may drop the reload, but ``entries_by_provider_ids`` keeps it
available unchanged.

Every write stamps ``updated_at`` with the transaction's ``tx.now``: the
extraction commit's hint fingerprint covers ``calendar_entries.updated_at``,
and ``tx.now`` never repeats, so a mirror write between an extraction's read
and its commit always changes the fingerprint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from selko.db import codec
from selko.db.connection import Database, Tx
from selko.db.errors import InvalidArgument, NotOwned

_ENTRY_TIMESTAMPS = frozenset({"start_at", "end_at", "provider_updated_at", "deleted_at"})
_ENTRY_COLUMNS = frozenset({
    "user_id", "integration_id", "calendar_id", "provider_event_id", "ical_uid",
    "recurring_event_id", "original_start", "title", "location", "start_at", "end_at",
    "all_day", "timezone", "status", "self_response", "etag", "sequence",
    "provider_updated_at", "origin", "deleted_at", "updated_at", "join_url",
})
_HINT_COLUMNS = frozenset({
    "user_id", "event_id", "calendar_entry_id", "source_email_id", "kind", "value_hash",
    "recurrence_id", "strength", "sequence", "dtstamp",
})
_STORED_COLUMNS = "id, ical_uid, original_start, deleted_at, join_url"
_BATCH = 500


def _timestamp(value: datetime | str | None) -> str | None:
    """A provider or caller timestamp as stored text; zone-less means UTC (Postgres session zone)."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return codec.to_timestamp(value)


def _owned_integration(tx: Tx, user_id: str, integration_id: str) -> None:
    if tx.execute(
        "SELECT 1 FROM integrations WHERE id = ? AND user_id = ?", (integration_id, user_id)
    ).fetchone() is None:
        raise NotOwned(f"integration {integration_id} is not owned by user {user_id}")


# ---------------------------------------------------------------------------
# calendar_mirror_state
# ---------------------------------------------------------------------------


def get_state(db: Database, user_id: str, integration_id: str, calendar_id: str) -> dict[str, Any] | None:
    """``{"sync_token": ...}`` for one mirrored calendar, or None before its first pass."""
    row = db.query_one(
        "SELECT sync_token FROM calendar_mirror_state "
        "WHERE integration_id = ? AND calendar_id = ? AND user_id = ?",
        (codec.to_id(integration_id), calendar_id, codec.to_id(user_id)),
    )
    return dict(row) if row is not None else None


def save_state(
    db: Database,
    user_id: str,
    integration_id: str,
    calendar_id: str,
    *,
    sync_token: str | None,
    window_start: datetime | str,
    window_end: datetime | str,
    full_resync: bool,
) -> None:
    """Record a successful pass (the service's upsert on ``integration_id, calendar_id``).

    ``last_success_at`` is now; ``last_full_resync_at`` is now after a full
    resync and NULL otherwise -- the service's payload always carried the
    column, so an incremental pass cleared it, and this keeps that.
    Failures reset to zero, the error code is cleared. Columns the service
    did not send (lease, ``next_poll_at``, ``last_error_at``) keep their values.
    """
    uid, iid = codec.to_id(user_id), codec.to_id(integration_id)
    with db.write() as tx:
        _owned_integration(tx, uid, iid)  # type: ignore[arg-type]
        tx.execute(
            "INSERT INTO calendar_mirror_state (integration_id, calendar_id, user_id, sync_token, "
            "window_start, window_end, last_success_at, last_full_resync_at, consecutive_failures, "
            "last_error_code, next_poll_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, ?) "
            "ON CONFLICT (integration_id, calendar_id) DO UPDATE SET "
            "user_id = excluded.user_id, sync_token = excluded.sync_token, "
            "window_start = excluded.window_start, window_end = excluded.window_end, "
            "last_success_at = excluded.last_success_at, "
            "last_full_resync_at = excluded.last_full_resync_at, "
            "consecutive_failures = 0, last_error_code = NULL, updated_at = excluded.updated_at",
            (iid, calendar_id, uid, sync_token, _timestamp(window_start), _timestamp(window_end),
             tx.now_text, tx.now_text if full_resync else None, tx.now_text, tx.now_text, tx.now_text),
        )


# ---------------------------------------------------------------------------
# calendar_entries
# ---------------------------------------------------------------------------


def upsert_entries(db: Database, user_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert or update mirrored entries on ``(integration_id, calendar_id, provider_event_id)``.

    Each row is ``calendar_mirror.entry_row``'s dict. Its ``user_id`` must be
    the caller's and its integration the user's (``NotOwned`` otherwise).
    On conflict every given column is overwritten (PostgREST's
    merge-duplicates); ``id`` and ``created_at`` are kept. ``updated_at`` is
    the transaction's time whatever the row says. Returns the stored
    ``id, ical_uid, original_start, deleted_at, join_url`` of each row, in
    input order. All rows are written in one transaction.
    """
    uid = codec.to_id(user_id)
    stored: list[dict[str, Any]] = []
    with db.write() as tx:
        checked: set[str] = set()
        for row in rows:
            unknown = set(row) - _ENTRY_COLUMNS
            if unknown:
                raise InvalidArgument(f"unknown calendar_entries columns: {sorted(unknown)}")
            if row.get("user_id") is not None and codec.to_id(row["user_id"]) != uid:
                raise NotOwned(f"entry row belongs to user {row['user_id']}, not {user_id}")
            iid = codec.to_id(row.get("integration_id"))
            if iid is None:
                raise InvalidArgument("calendar entry needs an integration_id")
            if iid not in checked:
                _owned_integration(tx, uid, iid)  # type: ignore[arg-type]
                checked.add(iid)
            values = {k: v for k, v in row.items() if k not in {"user_id", "integration_id", "updated_at"}}
            for column in _ENTRY_TIMESTAMPS & values.keys():
                values[column] = _timestamp(values[column])
            values = tx.schema.encode("calendar_entries", values)
            values.update(user_id=uid, integration_id=iid, updated_at=tx.now_text)
            cols = ["id", "created_at", *values]
            params = [codec.new_id(), tx.now_text, *values.values()]
            update = ", ".join(
                f"{c} = excluded.{c}" for c in values
                if c not in {"integration_id", "calendar_id", "provider_event_id"}
            )
            found = tx.execute(
                f"INSERT INTO calendar_entries ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
                f"ON CONFLICT (integration_id, calendar_id, provider_event_id) DO UPDATE SET {update} "
                f"RETURNING {_STORED_COLUMNS}",
                params,
            ).fetchone()
            stored.append(dict(found))
    return stored


def entries_by_provider_ids(
    db: Database, user_id: str, provider_event_ids: list[str]
) -> list[dict[str, Any]]:
    """``id, ical_uid, original_start, deleted_at, join_url`` of the user's entries
    with these provider ids (any integration or calendar, as the service's query)."""
    uid = codec.to_id(user_id)
    out: list[dict[str, Any]] = []
    ids = [i for i in provider_event_ids if i]
    for start in range(0, len(ids), _BATCH):
        chunk = ids[start : start + _BATCH]
        rows = db.query(
            f"SELECT {_STORED_COLUMNS} FROM calendar_entries "
            f"WHERE user_id = ? AND provider_event_id IN ({', '.join('?' for _ in chunk)})",
            (uid, *chunk),
        )
        out.extend(dict(r) for r in rows)
    return out


def indexable_entries(db: Database, user_id: str, limit: int = 500) -> list[dict[str, Any]]:
    """``id, ical_uid, original_start`` of up to ``limit`` live entries carrying an iCalUID.

    The service's query had no ORDER BY; this takes the oldest rows first
    (``created_at``, then insertion order) so repeated passes are deterministic.
    """
    rows = db.query(
        "SELECT id, ical_uid, original_start FROM calendar_entries "
        "WHERE user_id = ? AND ical_uid IS NOT NULL AND deleted_at IS NULL "
        "ORDER BY created_at, rowid LIMIT ?",
        (codec.to_id(user_id), limit),
    )
    return [dict(r) for r in rows]


def hinted_entry_ids(db: Database, user_id: str) -> set[str]:
    """Ids of the user's calendar entries that already have at least one hint."""
    rows = db.query(
        "SELECT DISTINCT calendar_entry_id FROM event_identity_hints "
        "WHERE user_id = ? AND calendar_entry_id IS NOT NULL",
        (codec.to_id(user_id),),
    )
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------
# event_identity_hints (calendar-entry side)
# ---------------------------------------------------------------------------


def upsert_entry_hints(db: Database, user_id: str, rows: list[dict[str, Any]]) -> int:
    """Insert or update hints on ``(calendar_entry_id, kind, value_hash, recurrence_id)``.

    Each row is ``{"user_id", "event_id": None, "calendar_entry_id", **hint.as_payload()}``.
    The entry must be the user's (``NotOwned`` otherwise) and ``event_id``
    must be empty: event hints are written only by the extraction commit.
    A column a row omits takes its default on insert and is left alone on
    update. Returns how many rows were written. One transaction.
    """
    uid = codec.to_id(user_id)
    with db.write() as tx:
        checked: set[str] = set()
        for row in rows:
            unknown = set(row) - _HINT_COLUMNS
            if unknown:
                raise InvalidArgument(f"unknown event_identity_hints columns: {sorted(unknown)}")
            if row.get("event_id") is not None:
                raise InvalidArgument("the mirror writes calendar-entry hints only")
            if row.get("user_id") is not None and codec.to_id(row["user_id"]) != uid:
                raise NotOwned(f"hint row belongs to user {row['user_id']}, not {user_id}")
            entry_id = codec.to_id(row.get("calendar_entry_id"))
            if entry_id is None:
                raise InvalidArgument("a mirror hint needs a calendar_entry_id")
            if entry_id not in checked:
                if tx.execute(
                    "SELECT 1 FROM calendar_entries WHERE id = ? AND user_id = ?", (entry_id, uid)
                ).fetchone() is None:
                    raise NotOwned(f"calendar entry {entry_id} is not owned by user {user_id}")
                checked.add(entry_id)
            values = {k: v for k, v in row.items() if k not in {"user_id", "event_id", "calendar_entry_id"}}
            if "dtstamp" in values:
                values["dtstamp"] = _timestamp(values["dtstamp"])
            values = tx.schema.encode("event_identity_hints", values)
            values.update(user_id=uid, calendar_entry_id=entry_id)
            cols = ["id", "created_at", *values]
            params = [codec.new_id(), tx.now_text, *values.values()]
            update = ", ".join(
                f"{c} = excluded.{c}" for c in values
                if c not in {"calendar_entry_id", "kind", "value_hash", "recurrence_id"}
            )
            tx.execute(
                f"INSERT INTO event_identity_hints ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
                f"ON CONFLICT (calendar_entry_id, kind, value_hash, recurrence_id) DO UPDATE SET {update}",
                params,
            )
        return len(rows)


__all__ = [
    "entries_by_provider_ids",
    "get_state",
    "hinted_entry_ids",
    "indexable_entries",
    "save_state",
    "upsert_entries",
    "upsert_entry_hints",
]
