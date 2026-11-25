"""Events: the fenced extraction commit, review decisions, and event reads.

Ports of the Postgres functions ``commit_email_extraction`` and
``set_event_review_status`` (docs/specs/sqlite-single-process/02-data-layer.md
§2.5) and of the ``events`` / ``event_sources`` / ``event_identity_hints``
queries the services and routes made through PostgREST (§3.1, §3.9).

The behaviour, the error messages and the result shapes are the Postgres ones.
Where Postgres semantics differ from SQLite's (``NULL`` ordering, ``LIKE`` case
folding, ``->>`` on JSON, ``::boolean`` and ``::timestamptz`` casts) the
Postgres meaning is implemented explicitly here.

The commit fence (§5.4): both fingerprints -- the candidate band and the rows
the identity hints name -- are computed by one Python function,
``resolution_fingerprint.candidate_fingerprint``, on the producer side
(`band_fingerprint`, `hint_fingerprint`) and inside the commit.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
from typing import Any

from selko.db import codec, errors
from selko.db.connection import Database, Tx
from selko.services.resolution_fingerprint import candidate_fingerprint

TERMINAL_STATUSES = ("processed", "skipped", "failed")
DECISION_ACTIONS = ("create", "update", "noop")
INTENTS = ("no_change", "apply", "review", "record_only")
REVIEW_STATUSES = ("pending_review", "active", "rejected", "cancelled")
CALENDAR_ACTIONS = ("upsert", "cancel")
HINT_KINDS = ("ical_uid", "provider_thread", "join_url", "management_url")
HINT_STRENGTHS = ("authoritative", "supporting")

# Fields a decision may set on an existing event (``v_fields ? 'key'``).
_UPDATABLE_TEXT = ("title", "location", "description", "importance", "recurrence_rule")


# ---------------------------------------------------------------------------
# Postgres value semantics
# ---------------------------------------------------------------------------


def jtext(obj: Any, key: str) -> str | None:
    """Postgres ``obj->>'key'``: the member as text, NULL when absent or JSON null.

    Strings come back unquoted, everything else as its JSON text, as jsonb
    renders it. ``->>`` on anything but an object is NULL.
    """
    if not isinstance(obj, dict) or key not in obj:
        return None
    return _elem_text(obj[key])


def _elem_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(value, separators=(", ", ": "), ensure_ascii=False)


def jobject(obj: Any, key: str) -> Any:
    """``COALESCE(obj->'key', '{}')``: the member when present (even JSON null), else {}."""
    if isinstance(obj, dict) and key in obj:
        return obj[key]
    return {}


def jarray(obj: Any, key: str) -> list[Any]:
    """``jsonb_array_elements(COALESCE(obj->'key', '[]'))``.

    An absent member is an empty array; a present member that is not an array
    is the error Postgres raises for it.
    """
    if not isinstance(obj, dict) or key not in obj:
        return []
    value = obj[key]
    if isinstance(value, list):
        return value
    kind = "an object" if isinstance(value, dict) else "a scalar"
    raise errors.InvalidArgument(f"cannot extract elements from {kind}")


_TRUE = {"t", "tr", "tru", "true", "y", "ye", "yes", "on", "1"}
_FALSE = {"f", "fa", "fal", "fals", "false", "n", "no", "of", "off", "0"}


def pg_bool(text: str | None) -> bool | None:
    """Postgres ``text::boolean``: t/true/yes/on/1 and their prefixes, any case."""
    if text is None:
        return None
    value = text.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise errors.InvalidArgument(f'invalid input syntax for type boolean: "{text}"')


def pg_timestamp(value: datetime | str | None) -> str | None:
    """Postgres ``::timestamptz`` into stored text. Naive values are UTC (the database zone)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day, tzinfo=UTC)
    else:
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text[-1:] in ("Z", "z") else text)
        except ValueError:
            raise errors.InvalidArgument(
                f'invalid input syntax for type timestamp with time zone: "{value}"'
            ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return codec.to_timestamp(parsed)


def pg_uuid(text: str | None) -> str | None:
    if text is None:
        return None
    try:
        return codec.to_id(text)
    except ValueError:
        raise errors.InvalidArgument(f'invalid input syntax for type uuid: "{text}"') from None


def pg_integer(text: str | None) -> int | None:
    if text is None:
        return None
    try:
        return int(text.strip())
    except ValueError:
        raise errors.InvalidArgument(f'invalid input syntax for type integer: "{text}"') from None


def pg_like(value: str | None, pattern: str) -> bool:
    """Postgres ``value LIKE pattern``: case-sensitive, ``%``/``_`` wildcards, ``\\`` escapes."""
    if value is None:
        return False
    out = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        out.append(".*" if ch == "%" else "." if ch == "_" else re.escape(ch))
        i += 1
    return re.fullmatch("".join(out), value, re.DOTALL) is not None


def json_text(value: Any) -> str:
    """A JSON column value as stored text; a JSON null is stored as ``null``, not SQL NULL."""
    return "null" if value is None else codec.to_json(value)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# The fence: one fingerprint implementation for producer and commit
# ---------------------------------------------------------------------------

_BAND_SQL = (
    "SELECT id, updated_at FROM events "
    "WHERE user_id = ? AND start_datetime >= ? AND start_datetime < ?"
)
_HINT_ROWS_SQL = """
SELECT e.id, e.updated_at FROM events e
WHERE e.user_id = :user_id AND e.id IN (
    SELECT DISTINCT h.event_id FROM event_identity_hints h
    WHERE h.user_id = :user_id AND h.event_id IS NOT NULL
      AND h.kind || '|' || h.value_hash || '|' || h.recurrence_id IN (SELECT value FROM json_each(:keys)))
UNION ALL
SELECT c.id, c.updated_at FROM calendar_entries c
WHERE c.user_id = :user_id AND c.id IN (
    SELECT DISTINCT h.calendar_entry_id FROM event_identity_hints h
    WHERE h.user_id = :user_id AND h.calendar_entry_id IS NOT NULL
      AND h.kind || '|' || h.value_hash || '|' || h.recurrence_id IN (SELECT value FROM json_each(:keys)))
"""


def _band_rows(execute, user_id: str, start: str | None, end: str | None) -> list[dict[str, Any]]:
    if start is None or end is None:
        # ``start_datetime >= NULL`` selects nothing.
        return []
    return [dict(r) for r in execute(_BAND_SQL, (user_id, start, end))]


def _hint_rows(execute, user_id: str, keys: Sequence[str]) -> list[dict[str, Any]]:
    return [dict(r) for r in execute(_HINT_ROWS_SQL, {"user_id": user_id, "keys": json.dumps(list(keys))})]


def hint_fingerprint(db: Database, user_id: str, hint_keys: Iterable[str]) -> str:
    """The fingerprint the commit re-checks over every row the hint keys name.

    Covers both entities a hint can name (events and mirrored calendar
    entries), so a mirror sync between decision and commit is seen by the fence.
    """
    keys = [k for k in hint_keys if k is not None]
    rows = _hint_rows(lambda sql, p: db.query(sql, p), codec.to_id(user_id), keys)  # type: ignore[arg-type]
    return candidate_fingerprint(rows)


# ---------------------------------------------------------------------------
# calendar work (owned by db/calendar_work.py)
# ---------------------------------------------------------------------------


def _enqueue_calendar_work(
    tx: Tx,
    event_id: str,
    user_id: str,
    action: str | None,
    desired_event: dict[str, Any] | None,
    expected_provider_revision: str | None,
    force_overwrite: bool | None,
) -> dict[str, Any]:
    from selko.db import calendar_work

    return calendar_work._enqueue_calendar_work(
        tx, event_id, user_id, action, desired_event, expected_provider_revision, force_overwrite
    )


# ---------------------------------------------------------------------------
# 39 commit_email_extraction
# ---------------------------------------------------------------------------


def commit_email_extraction(
    db: Database,
    email_id: str,
    worker_id: str,
    generation: int,
    decisions: list[dict[str, Any]] | None,
    terminal: str,
) -> dict[str, Any]:
    """Write one email's extraction decisions atomically, fenced by lease and band.

    Returns ``{"fenced": True, "applied": 0}`` when the lease moved on,
    ``{"fenced": False, "conflict": True, "conflicting_indexes": [i]}`` when a
    band or hint fingerprint changed since decision ``i`` was computed, and
    otherwise ``{"fenced": False, "conflict": False, "applied": n,
    "event_ids": [...created ids]}``.
    """
    if terminal is not None and terminal not in TERMINAL_STATUSES:
        raise errors.InvalidArgument(f"invalid extraction terminal status: {terminal}")
    email_id = pg_uuid(str(email_id))  # type: ignore[assignment]
    if decisions is None:
        decisions = []
    if not isinstance(decisions, list):
        raise errors.InvalidArgument("cannot extract elements from a scalar")

    with db.write() as tx:
        email = tx.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
        if email is None:
            raise errors.NotFound(f"email {email_id} not found")
        if email["locked_by"] != worker_id or email["lock_generation"] != generation:
            return {"fenced": True, "applied": 0}
        user_id: str = email["user_id"]

        # Envelope validation over every decision before anything else (in
        # Postgres this is the advisory-lock loop; a NULL action is filtered
        # out of it by ``NULL <> 'noop'``).
        for decision in decisions:
            action = jtext(decision, "action")
            if action is None or action == "noop":
                continue
            if (action not in DECISION_ACTIONS or jtext(decision, "window_start") is None
                    or jtext(decision, "window_end") is None):
                raise errors.InvalidArgument("invalid extraction decision envelope")
            jarray(decision, "hints")

        # The fence: every decision's band, and the rows its hints name.
        execute = lambda sql, p: tx.execute(sql, p).fetchall()
        for index, decision in enumerate(decisions):
            if jtext(decision, "action") == "noop":
                continue
            start = pg_timestamp(jtext(decision, "window_start"))
            end = pg_timestamp(jtext(decision, "window_end"))
            actual = candidate_fingerprint(_band_rows(execute, user_id, start, end))
            if actual != jtext(decision, "expected_fingerprint"):
                return {"fenced": False, "conflict": True, "conflicting_indexes": [index]}
            hint_keys = jarray(decision, "hint_keys")
            if hint_keys:
                keys = [k for k in (_elem_text(v) for v in hint_keys) if k is not None]
                actual = candidate_fingerprint(_hint_rows(execute, user_id, keys))
                if actual != jtext(decision, "expected_hint_fingerprint"):
                    return {"fenced": False, "conflict": True, "conflicting_indexes": [index]}

        applied = 0
        event_ids: list[str] = []
        for decision in decisions:
            event_id = _apply_decision(tx, email_id, user_id, decision, event_ids)
            if event_id is not None:
                applied += 1

        tx.execute(
            "UPDATE emails SET processing_status = ?, processing_error = NULL, "
            "processed_at = CASE WHEN ? = 'processed' THEN ? ELSE processed_at END, "
            "locked_by = NULL, locked_until = NULL WHERE id = ?",
            (terminal, terminal, tx.now_text, email_id),
        )
    return {"fenced": False, "conflict": False, "applied": applied, "event_ids": event_ids}


def _apply_decision(
    tx: Tx, email_id: str, user_id: str, decision: Any, created: list[str]
) -> str | None:
    """One decision of the write loop; returns its event id, or None for a noop."""
    action = jtext(decision, "action")
    if action == "noop":
        return None
    fields = jobject(decision, "fields")
    source = jobject(decision, "source")
    source_origin = jtext(source, "source_origin") or "email"
    source_type = jtext(source, "source_type") or "new_invitation"
    google_source_id = jtext(source, "google_calendar_source_event_id")
    change_set = source.get("change_set") if isinstance(source, dict) else None
    snapshot = source.get("event_snapshot_before") if isinstance(source, dict) else None
    has_change = (isinstance(change_set, dict) and change_set != {}
                  and isinstance(snapshot, dict) and snapshot != {})

    intent = jtext(decision, "intent")
    if intent is None or intent not in INTENTS:
        raise errors.InvalidArgument(
            f"extraction decision requires a known intent (got {intent if intent is not None else '<missing>'})"
        )
    if intent == "no_change" and has_change:
        raise errors.InvalidArgument("intent no_change cannot carry a change_set")
    if intent in ("apply", "review") and not has_change:
        raise errors.InvalidArgument(f"intent {intent} requires a change_set and snapshot")

    review_status: str | None = None
    calendar_action = "upsert"
    enqueue = False
    if intent == "record_only":
        # record_only touches neither the event nor any proposal: a later email
        # about a declined event keeps its provenance and hints only.
        if action is not None and action != "update":
            raise errors.InvalidArgument("intent record_only requires an update decision")
        event_id = _owned_update_target(tx, decision, user_id)
    else:
        review_status = jtext(fields, "review_status")
        if review_status is None:
            raise errors.InvalidArgument("extraction decision requires an explicit review_status")
        if review_status not in REVIEW_STATUSES:
            raise errors.InvalidArgument(f"invalid extraction review status {review_status}")
        if intent == "review" and review_status != "active":
            raise errors.InvalidArgument(
                f"a change held for review requires review_status active, got {review_status}"
            )
        calendar_action = jtext(fields, "calendar_action") or "upsert"
        if calendar_action not in CALENDAR_ACTIONS:
            raise errors.InvalidArgument(f"invalid extraction calendar action {calendar_action}")
        apply_fields = intent in ("no_change", "apply")
        enqueue = review_status == "active" and apply_fields

        if action == "create":
            event_id = codec.new_id()
            all_day = pg_bool(jtext(fields, "all_day"))
            tx.execute(
                "INSERT INTO events (id, user_id, title, start_datetime, end_datetime, all_day, "
                "location, description, importance, review_status, recurrence_rule, "
                "google_calendar_event_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id, user_id, jtext(fields, "title"),
                    pg_timestamp(jtext(fields, "start_datetime")),
                    pg_timestamp(jtext(fields, "end_datetime")),
                    int(all_day) if all_day is not None else 0,
                    jtext(fields, "location"), jtext(fields, "description"),
                    jtext(fields, "importance") or "action_required",
                    review_status, jtext(fields, "recurrence_rule"),
                    jtext(fields, "google_calendar_event_id"), tx.now_text, tx.now_text,
                ),
            )
            created.append(event_id)
        else:
            event_id = _owned_update_target(tx, decision, user_id)
            if apply_fields:
                sets: list[str] = []
                params: list[Any] = []
                present = fields if isinstance(fields, dict) else {}
                for key in ("start_datetime", "end_datetime"):
                    if key in present:
                        sets.append(f"{key} = ?")
                        params.append(pg_timestamp(jtext(fields, key)))
                if "all_day" in present:
                    value = pg_bool(jtext(fields, "all_day"))
                    sets.append("all_day = ?")
                    params.append(int(value) if value is not None else None)
                for key in _UPDATABLE_TEXT:
                    if key in present:
                        sets.append(f"{key} = ?")
                        params.append(jtext(fields, key))
                sets += ["review_status = ?", "updated_at = ?"]
                params += [review_status, tx.now_text, event_id]
                tx.execute(f"UPDATE events SET {', '.join(sets)} WHERE id = ?", params)
            else:
                # intent 'review': the proposal owns the change; only the lane is asserted.
                tx.execute(
                    "UPDATE events SET review_status = ?, updated_at = ? WHERE id = ?",
                    (review_status, tx.now_text, event_id),
                )

    extracted = source.get("extracted_data", {}) if isinstance(source, dict) else {}
    if source_origin == "google_calendar":
        source_id = codec.new_id()
        tx.execute(
            "INSERT INTO event_sources (id, event_id, source_origin, google_calendar_source_event_id, "
            "source_type, extracted_data, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source_id, event_id, source_origin, google_source_id, source_type,
             json_text(extracted), tx.now_text),
        )
    else:
        row = tx.execute(
            "INSERT INTO event_sources (id, event_id, email_id, source_origin, source_type, "
            "extracted_data, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (event_id, email_id) WHERE source_origin = 'email' DO UPDATE SET "
            "source_type = excluded.source_type, extracted_data = excluded.extracted_data "
            "RETURNING id",
            (codec.new_id(), event_id, pg_uuid(jtext(source, "email_id")) or email_id,
             source_origin, source_type, json_text(extracted), tx.now_text),
        ).fetchone()
        source_id = row["id"]

    for extra in jarray(source, "extra_sources"):
        if (jtext(extra, "source_origin") or "email") == "google_calendar":
            tx.execute(
                "INSERT INTO event_sources (id, event_id, source_origin, google_calendar_source_event_id, "
                "source_type, extracted_data, created_at) VALUES (?, ?, 'google_calendar', ?, ?, ?, ?)",
                (codec.new_id(), event_id, jtext(extra, "google_calendar_source_event_id"),
                 jtext(extra, "source_type") or source_type,
                 json_text(extra.get("extracted_data", {})), tx.now_text),
            )

    if intent in ("apply", "review"):
        tx.execute(
            "UPDATE event_change_proposals SET status = 'superseded', "
            "resolution_reason = 'superseded_by_newer_proposal', resolved_at = ?, updated_at = ? "
            "WHERE event_id = ? AND status = 'pending' AND source_id <> ?",
            (tx.now_text, tx.now_text, event_id, source_id),
        )
        status = "applied" if intent == "apply" else "pending"
        # A fresh row gets no resolved_at (as in Postgres); a re-commit of the
        # same source stamps it unless the proposal is pending again.
        tx.execute(
            "INSERT INTO event_change_proposals (id, event_id, user_id, source_id, kind, status, "
            "change_set, event_snapshot_before, resolution_reason, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (source_id) DO UPDATE SET status = excluded.status, "
            "change_set = excluded.change_set, event_snapshot_before = excluded.event_snapshot_before, "
            "resolution_reason = excluded.resolution_reason, "
            "resolved_at = CASE WHEN excluded.status = 'pending' THEN NULL ELSE ? END, updated_at = ?",
            (codec.new_id(), event_id, user_id, source_id,
             "cancellation" if source_type == "cancellation" else "material_update",
             status, json_text(change_set), json_text(snapshot),
             "automatic_apply" if intent == "apply" else None,
             tx.now_text, tx.now_text, tx.now_text, tx.now_text),
        )

    if enqueue:
        desired = None
        if calendar_action != "cancel":
            all_day = pg_bool(jtext(fields, "all_day"))
            desired = {
                "title": jtext(fields, "title"),
                "start_datetime": jtext(fields, "start_datetime"),
                "end_datetime": jtext(fields, "end_datetime"),
                "all_day": all_day if all_day is not None else False,
                "location": jtext(fields, "location"),
                "description": jtext(fields, "description"),
                "importance": jtext(fields, "importance") or "action_required",
            }
        _enqueue_calendar_work(tx, event_id, user_id, calendar_action, desired, None, False)

    for hint in jarray(decision, "hints"):
        _upsert_hint(tx, user_id, event_id, email_id, hint)
    return event_id


def _owned_update_target(tx: Tx, decision: Any, user_id: str) -> str:
    event_id = pg_uuid(jtext(decision, "event_id"))
    if event_id is None:
        raise errors.InvalidArgument("update decision requires event_id")
    if tx.execute("SELECT 1 FROM events WHERE id = ? AND user_id = ?", (event_id, user_id)).fetchone() is None:
        raise errors.NotOwned(f"event {event_id} is not owned by email user")
    return event_id


def _upsert_hint(tx: Tx, user_id: str, event_id: str, email_id: str, hint: Any) -> None:
    kind = jtext(hint, "kind")
    value_hash = jtext(hint, "value_hash")
    strength = jtext(hint, "strength")
    recurrence = jtext(hint, "recurrence_id") or ""
    if ((kind is not None and kind not in HINT_KINDS)
            or (strength is not None and strength not in HINT_STRENGTHS)
            or not value_hash):
        raise errors.InvalidArgument("invalid identity hint")
    sequence_text = jtext(hint, "sequence")
    sequence = pg_integer(sequence_text) if sequence_text not in (None, "") else None
    dtstamp_text = jtext(hint, "dtstamp")
    dtstamp = pg_timestamp(dtstamp_text) if dtstamp_text not in (None, "") else None
    tx.execute(
        "INSERT INTO event_identity_hints (id, user_id, event_id, source_email_id, kind, value_hash, "
        "recurrence_id, strength, sequence, dtstamp, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (event_id, kind, value_hash, recurrence_id) DO UPDATE SET "
        "source_email_id = excluded.source_email_id, strength = excluded.strength, "
        "sequence = CASE WHEN excluded.kind = 'ical_uid' AND excluded.sequence >= event_identity_hints.sequence "
        "THEN excluded.sequence ELSE event_identity_hints.sequence END, "
        "dtstamp = CASE WHEN excluded.kind = 'ical_uid' AND excluded.sequence >= event_identity_hints.sequence "
        "THEN excluded.dtstamp ELSE event_identity_hints.dtstamp END",
        (codec.new_id(), user_id, event_id, email_id, kind, value_hash, recurrence, strength,
         sequence if sequence is not None else 0, dtstamp, tx.now_text),
    )


# ---------------------------------------------------------------------------
# 40 set_event_review_status
# ---------------------------------------------------------------------------


def set_event_review_status(db: Database, user_id: str | None, event_id: str, review_status: str) -> dict[str, Any]:
    """Approve (``active``, queueing a calendar upsert) or reject one of the user's events."""
    if review_status is not None and review_status not in ("active", "rejected"):
        raise errors.InvalidArgument(f"invalid event review status {review_status}")
    if user_id is None:
        raise errors.NotOwned("authentication required")
    user_id = codec.to_id(user_id)
    event_id = pg_uuid(str(event_id))  # type: ignore[assignment]
    item: dict[str, Any] | None = None
    with db.write() as tx:
        event = tx.schema.decode("events", tx.execute(
            "SELECT * FROM events WHERE id = ? AND user_id = ?", (event_id, user_id)
        ).fetchone())
        if event is None:
            raise errors.NotOwned(f"event {event_id} is not owned by the caller")
        if review_status == "active":
            # Before the enqueue, so its declined-event guard sees this decision.
            tx.execute("UPDATE events SET review_status = 'active', updated_at = ? WHERE id = ?",
                       (tx.now_text, event_id))
            item = _enqueue_calendar_work(tx, event_id, event["user_id"], "upsert", {
                "title": event["title"], "start_datetime": event["start_datetime"],
                "end_datetime": event["end_datetime"], "all_day": event["all_day"],
                "location": event["location"], "description": event["description"],
                "importance": event["importance"], "source_attribution": event["source_attribution"],
            }, None, False)
        else:
            tx.execute("UPDATE events SET review_status = 'rejected', updated_at = ? WHERE id = ?",
                       (tx.now_text, event_id))
    return {
        "event_id": event_id, "review_status": review_status,
        "work_item_id": item["id"] if item else None,
        "generation": item["generation"] if item else None,
    }


# ---------------------------------------------------------------------------
# Reads and small writes the services and routes made through PostgREST
# ---------------------------------------------------------------------------


def _decode(db: Database, table: str, rows: Iterable[Any]) -> list[dict[str, Any]]:
    return [db.schema.decode(table, r) for r in rows]  # type: ignore[misc]


def get(db: Database, user_id: str, event_id: str) -> dict[str, Any] | None:
    """One of the user's events (``select * … maybe_single``), or None."""
    row = db.query_one("SELECT * FROM events WHERE id = ? AND user_id = ?",
                       (codec.to_id(event_id), codec.to_id(user_id)))
    return db.schema.decode("events", row)


def get_with_work_items(db: Database, user_id: str, event_id: str) -> dict[str, Any] | None:
    """The event plus ``calendar_work_items(status, action, generation, failure_code)``."""
    event = get(db, user_id, event_id)
    if event is None:
        return None
    rows = db.query(
        "SELECT status, action, generation, failure_code FROM calendar_work_items "
        "WHERE event_id = ? ORDER BY generation, id", (event["id"],),
    )
    event["calendar_work_items"] = [dict(r) for r in rows]
    return event


def get_many(db: Database, user_id: str, event_ids: Iterable[str]) -> list[dict[str, Any]]:
    ids = [codec.to_id(i) for i in event_ids]
    if not ids:
        return []
    rows = db.query(
        "SELECT * FROM events WHERE user_id = ? AND id IN (SELECT value FROM json_each(?)) ORDER BY id",
        (codec.to_id(user_id), json.dumps(ids)),
    )
    return _decode(db, "events", rows)


def in_window(db: Database, user_id: str, start: Any, end: Any) -> list[dict[str, Any]]:
    """Events starting in ``[start, end)``: the band whose fingerprint the commit re-checks."""
    rows = db.query(
        "SELECT * FROM events WHERE user_id = ? AND start_datetime >= ? AND start_datetime < ? ORDER BY id",
        (codec.to_id(user_id), pg_timestamp(start), pg_timestamp(end)),
    )
    return _decode(db, "events", rows)


def by_provider_event_id(db: Database, user_id: str, provider_event_id: str) -> dict[str, Any] | None:
    """The oldest event bound to a provider event id, whatever its review status."""
    row = db.query_one(
        "SELECT * FROM events WHERE user_id = ? AND google_calendar_event_id = ? "
        "ORDER BY created_at, id LIMIT 1",
        (codec.to_id(user_id), provider_event_id),
    )
    return db.schema.decode("events", row)


def pending_in_window(db: Database, user_id: str, start_min: Any, start_max: Any) -> list[dict[str, Any]]:
    """New-lane events starting in ``[start_min, start_max]`` (both inclusive)."""
    rows = db.query(
        "SELECT id, title, start_datetime, end_datetime, location, description FROM events "
        "WHERE user_id = ? AND review_status = 'pending_review' "
        "AND start_datetime >= ? AND start_datetime <= ? ORDER BY start_datetime, id",
        (codec.to_id(user_id), pg_timestamp(start_min), pg_timestamp(start_max)),
    )
    return [dict(r) for r in rows]


def reject_pending_in_tx(tx: Tx, user_id: str, event_id: str) -> int:
    """Compare-and-set one New-lane event to rejected inside ``tx``; the rows changed (0 or 1)."""
    return tx.execute(
        "UPDATE events SET review_status = 'rejected', updated_at = ? "
        "WHERE id = ? AND user_id = ? AND review_status = 'pending_review'",
        (tx.now_text, codec.to_id(event_id), codec.to_id(user_id)),
    ).rowcount


def retire_pending(db: Database, user_id: str, event_id: str) -> bool:
    """Compare-and-set a New-lane event to rejected; False when it had left New already."""
    with db.write() as tx:
        return reject_pending_in_tx(tx, user_id, event_id) > 0


def event_ids_for_email(db: Database, user_id: str, email_id: str) -> list[str]:
    """The user's events with a source row for this email (routes/emails.py)."""
    rows = db.query(
        "SELECT s.event_id FROM event_sources s JOIN events e ON e.id = s.event_id "
        "WHERE s.email_id = ? AND e.user_id = ? ORDER BY s.created_at, s.id",
        (codec.to_id(email_id), codec.to_id(user_id)),
    )
    return [r["event_id"] for r in rows]


def source_types_for_email(db: Database, email_id: str) -> list[str]:
    rows = db.query("SELECT source_type FROM event_sources WHERE email_id = ? ORDER BY created_at, id",
                    (codec.to_id(email_id),))
    return [r["source_type"] for r in rows]


def source_email_dates(db: Database, event_id: str) -> list[str | None]:
    """``emails.date_sent`` of each source (``event_sources.select('emails(date_sent)')``)."""
    rows = db.query(
        "SELECT m.date_sent FROM event_sources s LEFT JOIN emails m ON m.id = s.email_id "
        "WHERE s.event_id = ? ORDER BY s.created_at, s.id", (codec.to_id(event_id),),
    )
    return [r["date_sent"] for r in rows]


def has_source_origin(db: Database, event_id: str, origin: str) -> bool:
    return db.query_one("SELECT 1 FROM event_sources WHERE event_id = ? AND source_origin = ? LIMIT 1",
                        (codec.to_id(event_id), origin)) is not None


def source_email_ids(db: Database, event_id: str) -> list[str]:
    rows = db.query(
        "SELECT email_id FROM event_sources WHERE event_id = ? AND email_id IS NOT NULL "
        "ORDER BY created_at, id", (codec.to_id(event_id),),
    )
    return [r["email_id"] for r in rows]


def sources(db: Database, event_id: str) -> list[dict[str, Any]]:
    """``id, source_type, source_origin`` of an event's sources."""
    rows = db.query("SELECT id, source_type, source_origin FROM event_sources WHERE event_id = ? "
                    "ORDER BY created_at, id", (codec.to_id(event_id),))
    return [dict(r) for r in rows]


def sources_with_emails(db: Database, event_id: str) -> list[dict[str, Any]]:
    """``event_sources(*, emails(*))`` ordered by created_at; ``emails`` is None without one."""
    srcs = _decode(db, "event_sources", db.query(
        "SELECT * FROM event_sources WHERE event_id = ? ORDER BY created_at, id", (codec.to_id(event_id),)
    ))
    email_ids = sorted({s["email_id"] for s in srcs if s.get("email_id")})
    emails: dict[str, dict[str, Any]] = {}
    if email_ids:
        for row in db.query("SELECT * FROM emails WHERE id IN (SELECT value FROM json_each(?))",
                            (json.dumps(email_ids),)):
            emails[row["id"]] = db.schema.decode("emails", row)  # type: ignore[assignment]
    for s in srcs:
        s["emails"] = emails.get(s["email_id"]) if s.get("email_id") else None
    return srcs


def hints_matching(
    db: Database, user_id: str, keys: Iterable[tuple[str, str, str]]
) -> dict[str, list[dict[str, Any]]]:
    """Hint rows per ``kind|value_hash|recurrence_id`` key (``_load_identity_candidates``)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for kind, value_hash, recurrence_id in keys:
        rows = db.query(
            "SELECT event_id, calendar_entry_id, kind, value_hash, recurrence_id, strength, sequence, dtstamp "
            "FROM event_identity_hints WHERE user_id = ? AND kind = ? AND value_hash = ? AND recurrence_id = ? "
            "ORDER BY created_at, id",
            (codec.to_id(user_id), kind, value_hash, recurrence_id),
        )
        out[f"{kind}|{value_hash}|{recurrence_id}"] = [dict(r) for r in rows]
    return out



# ---------------------------------------------------------------------------
# Neighbouring tables the extraction pipeline reads and writes
# (services/events.py §3.9: emails, email_calendar_components, calendar_entries)
# ---------------------------------------------------------------------------

# The columns ``mark_email_status`` may write; identifiers never come from input.
EMAIL_STATUS_COLUMNS = (
    "processing_status", "processing_error", "processed_at",
    "processing_outcome", "processing_explanation", "processing_result",
)


def mark_email_status(db: Database, email_id: str, fields: dict[str, Any]) -> bool:
    """Write an email's processing status fields (worker-scoped; the email is claimed).

    ``processed_at=True`` stamps the transaction time. Returns whether a row changed.
    """
    unknown = set(fields) - set(EMAIL_STATUS_COLUMNS)
    if unknown:
        raise errors.InvalidArgument(f"not an email status column: {sorted(unknown)}")
    if not fields:
        return False
    with db.write() as tx:
        values = dict(fields)
        if values.get("processed_at") is True:
            values["processed_at"] = tx.now_text
        values = tx.schema.encode("emails", values)
        cols = ", ".join(f"{c} = ?" for c in values)
        cur = tx.execute(f"UPDATE emails SET {cols} WHERE id = ?",
                         (*values.values(), codec.to_id(email_id)))
        return cur.rowcount > 0


def email_identity_context(db: Database, email_id: str) -> dict[str, Any]:
    """``email_provider, thread_id, subject, body_text`` of one email, or {}."""
    row = db.query_one(
        "SELECT email_provider, thread_id, subject, body_text FROM emails WHERE id = ?",
        (codec.to_id(email_id),),
    )
    return dict(row) if row is not None else {}


def email_calendar_components(db: Database, email_id: str) -> list[dict[str, Any]]:
    """An email's parsed calendar components, in component order."""
    rows = db.query(
        "SELECT component_index, method, uid_hash, recurrence_id, sequence, dtstamp "
        "FROM email_calendar_components WHERE email_id = ? ORDER BY component_index",
        (codec.to_id(email_id),),
    )
    return [dict(r) for r in rows]


def email_has_component_method(db: Database, email_id: str, method: str) -> bool:
    return db.query_one(
        "SELECT 1 FROM email_calendar_components WHERE email_id = ? AND method = ? LIMIT 1",
        (codec.to_id(email_id), method),
    ) is not None


def calendar_entry_hint_exists(db: Database, user_id: str, kind: str, value_hashes: Iterable[str]) -> bool:
    """Whether any of the user's mirrored calendar entries carries one of these hints."""
    hashes = sorted({h for h in value_hashes if h})
    if not hashes:
        return False
    return db.query_one(
        "SELECT 1 FROM event_identity_hints WHERE user_id = ? AND kind = ? "
        "AND value_hash IN (SELECT value FROM json_each(?)) AND calendar_entry_id IS NOT NULL LIMIT 1",
        (codec.to_id(user_id), kind, json.dumps(hashes)),
    ) is not None


_ENTRY_COLUMNS = "id, title, start_at, end_at, location, ical_uid, provider_event_id, updated_at"


def mirror_entries_by_ids(db: Database, user_id: str, entry_ids: Iterable[str]) -> list[dict[str, Any]]:
    """The user's live (not deleted) mirrored calendar entries with these ids."""
    ids = sorted({codec.to_id(i) for i in entry_ids if i})  # type: ignore[type-var]
    if not ids:
        return []
    rows = db.query(
        f"SELECT {_ENTRY_COLUMNS} FROM calendar_entries WHERE user_id = ? "
        "AND id IN (SELECT value FROM json_each(?)) AND deleted_at IS NULL ORDER BY id",
        (codec.to_id(user_id), json.dumps(ids)),
    )
    return [dict(r) for r in rows]


def mirror_entries_in_window(db: Database, user_id: str, start: Any, end: Any) -> list[dict[str, Any]]:
    """The user's live mirrored calendar entries starting in ``[start, end)``."""
    rows = db.query(
        f"SELECT {_ENTRY_COLUMNS} FROM calendar_entries WHERE user_id = ? "
        "AND start_at >= ? AND start_at < ? AND deleted_at IS NULL ORDER BY start_at, id",
        (codec.to_id(user_id), pg_timestamp(start), pg_timestamp(end)),
    )
    return [dict(r) for r in rows]


def email_outcome(db: Database, email_id: str) -> dict[str, Any] | None:
    """``id, processing_outcome, processing_result`` of one email, or None."""
    row = db.query_one(
        "SELECT id, processing_outcome, processing_result FROM emails WHERE id = ?",
        (codec.to_id(email_id),),
    )
    return db.schema.decode("emails", row)


def event_owner(db: Database, event_id: str) -> str | None:
    """The user who owns an event (for service callers handed only an event id)."""
    row = db.query_one("SELECT user_id FROM events WHERE id = ?", (codec.to_id(event_id),))
    return row["user_id"] if row is not None else None


def band_fingerprint(db: Database, user_id: str, window_start: Any, window_end: Any) -> str:
    """The fingerprint the commit re-checks for a decision's local-day band."""
    rows = _band_rows(
        lambda sql, p: db.query(sql, p), codec.to_id(user_id),  # type: ignore[arg-type]
        pg_timestamp(window_start), pg_timestamp(window_end),
    )
    return candidate_fingerprint(rows)


__all__ = [
    "band_fingerprint",
    "calendar_entry_hint_exists", "email_calendar_components", "email_has_component_method",
    "email_identity_context", "email_outcome", "event_owner", "mark_email_status",
    "mirror_entries_by_ids", "mirror_entries_in_window", "by_provider_event_id", "commit_email_extraction", "event_ids_for_email",
    "get", "get_many", "get_with_work_items", "has_source_origin", "hint_fingerprint",
    "hints_matching", "in_window", "pending_in_window", "retire_pending", "set_event_review_status",
    "source_email_dates", "source_email_ids", "source_types_for_email", "sources",
    "sources_with_emails",
]
