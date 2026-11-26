"""Reads and writes behind the web app's data API (03-api-auth-web.md §A, E1-E19).

The browser used to query these tables directly with row-level security; now
every function here takes the verified user's id and filters by it. Orderings
reproduce PostgREST's: ascending sorts NULLs last, descending NULLs first.
Embedded relations get a fixed order (sources and proposals by
``created_at, id``; work items by ``generation, id``).
"""

from __future__ import annotations

from typing import Any

from selko.db.codec import to_timestamp
from selko.db.connection import Database
from selko.db.errors import UniqueViolation

EVENT_COLUMNS = (
    "id, user_id, title, start_datetime, end_datetime, all_day, location, description, "
    "source_attribution, google_calendar_event_id, synced_at, created_at, updated_at, "
    "importance, recurrence_rule, recovery_id, review_status"
)
SOURCE_COLUMNS = (
    "s.id, s.event_id, s.email_id, s.source_type, s.extracted_data, s.created_at, "
    "s.source_origin, s.google_calendar_source_event_id"
)
PROPOSAL_COLUMNS = (
    "id, event_id, user_id, source_id, kind, status, change_set, event_snapshot_before, "
    "resolution_reason, created_at, resolved_at, updated_at"
)
WORK_ITEM_COLUMNS = (
    "id, event_id, user_id, action, generation, status, provider_event_id, "
    "expected_provider_revision, force_overwrite, attempts, max_attempts, next_retry_at, "
    "failure_code, failure_detail, created_at, updated_at, completed_at"
)
EDITABLE_EVENT_FIELDS = ("title", "start_datetime", "end_datetime", "all_day", "location", "description")


def _marks(values: list[Any]) -> str:
    return ", ".join("?" for _ in values)


def _decode(db: Database, table: str, rows: list[Any]) -> list[dict[str, Any]]:
    return [db.schema.decode(table, r) for r in rows]  # type: ignore[misc]


# --- events -----------------------------------------------------------------


def events_with_relations(
    db: Database, user_id: str, event_ids: list[str], *, exclude_pending_proposals: bool = False
) -> list[dict[str, Any]]:
    """Owned events in ``event_ids`` order, each with its sources, proposals and work items."""
    if not event_ids:
        return []
    events = {
        r["id"]: r
        for r in _decode(
            db, "events",
            db.query(f"SELECT {EVENT_COLUMNS} FROM events WHERE user_id = ? AND id IN ({_marks(event_ids)})",
                     (user_id, *event_ids)),
        )
    }
    ids = [i for i in event_ids if i in events]
    for event in events.values():
        event["event_sources"], event["event_change_proposals"], event["calendar_work_items"] = [], [], []
    if not ids:
        return []
    for row in db.query(
        f"SELECT {SOURCE_COLUMNS}, e.id AS e_id, e.subject AS e_subject, e.from_email AS e_from_email,"
        " e.from_name AS e_from_name, e.date_sent AS e_date_sent"
        f" FROM event_sources s LEFT JOIN emails e ON e.id = s.email_id AND e.user_id = ?"
        f" WHERE s.event_id IN ({_marks(ids)}) ORDER BY s.created_at, s.id",
        (user_id, *ids),
    ):
        source = db.schema.decode("event_sources", {k: row[k] for k in row.keys() if not k.startswith("e_")})
        source["emails"] = (
            {"id": row["e_id"], "subject": row["e_subject"], "from_email": row["e_from_email"],
             "from_name": row["e_from_name"], "date_sent": row["e_date_sent"]}
            if row["e_id"] is not None else None
        )
        events[source["event_id"]]["event_sources"].append(source)
    status_filter = " AND status <> 'pending'" if exclude_pending_proposals else ""
    for proposal in _decode(db, "event_change_proposals", db.query(
        f"SELECT {PROPOSAL_COLUMNS} FROM event_change_proposals WHERE user_id = ? AND event_id IN ({_marks(ids)})"
        f"{status_filter} ORDER BY created_at, id",
        (user_id, *ids),
    )):
        events[proposal["event_id"]]["event_change_proposals"].append(proposal)
    for item in _decode(db, "calendar_work_items", db.query(
        f"SELECT {WORK_ITEM_COLUMNS} FROM calendar_work_items WHERE user_id = ? AND event_id IN ({_marks(ids)})"
        " ORDER BY generation, id",
        (user_id, *ids),
    )):
        events[item["event_id"]]["calendar_work_items"].append(item)
    return [events[i] for i in ids]


_REVIEW_WHERE = (
    " FROM events e WHERE e.user_id = ?"
    " AND e.review_status IN ('pending_review', 'active')"
    " AND (e.end_datetime >= ? OR (e.end_datetime IS NULL AND e.start_datetime >= ?)"
    "      OR (e.end_datetime IS NULL AND e.start_datetime IS NULL))"
    " AND (e.review_status = 'pending_review' OR EXISTS ("
    "      SELECT 1 FROM event_change_proposals p WHERE p.event_id = e.id AND p.status = 'pending'))"
)


def review_event_ids(db: Database, user_id: str, now: str, limit: int = 200) -> tuple[list[str], int]:
    """E1: upcoming owned events that are new, or active with a pending change.

    The soonest ``limit`` of them, and how many there are in all. Unbounded, a
    queue of 15,000 pending events answered 17 MB in one response, held in
    memory several times over while it was built.
    """
    total = db.query_one("SELECT count(*)" + _REVIEW_WHERE, (user_id, now, now))[0]
    ids = [r[0] for r in db.query(
        "SELECT e.id" + _REVIEW_WHERE + " ORDER BY e.start_datetime IS NULL, e.start_datetime, e.id LIMIT ?",
        (user_id, now, now, limit),
    )]
    return ids, int(total)


def activity_page(db: Database, user_id: str, limit: int, offset: int) -> tuple[list[str], int]:
    """E2: decided events, most recently changed first."""
    where = "user_id = ? AND review_status IN ('active', 'rejected', 'cancelled')"
    total = db.query_one(f"SELECT count(*) FROM events WHERE {where}", (user_id,))[0]
    ids = [r[0] for r in db.query(
        f"SELECT id FROM events WHERE {where} ORDER BY updated_at IS NOT NULL, updated_at DESC, id DESC"
        " LIMIT ? OFFSET ?",
        (user_id, limit, offset),
    )]
    return ids, int(total)


def update_event(db: Database, user_id: str, event_id: str, fields: dict[str, Any]) -> bool:
    """E4: edit an owned event's own fields. No calendar work (unchanged behaviour)."""
    unknown = set(fields) - set(EDITABLE_EVENT_FIELDS)
    if unknown or not fields:
        raise ValueError(f"not editable: {sorted(unknown) or 'nothing given'}")
    values = db.schema.encode("events", dict(fields))
    for key in ("start_datetime", "end_datetime"):
        if isinstance(values.get(key), str):
            values[key] = to_timestamp(values[key])
    assignments = ", ".join(f"{k} = ?" for k in values)
    with db.write() as tx:
        cur = tx.execute(
            f"UPDATE events SET {assignments} WHERE id = ? AND user_id = ?",
            (*values.values(), event_id, user_id),
        )
        return cur.rowcount == 1


# --- emails -----------------------------------------------------------------


def email_history(db: Database, user_id: str, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    """E7: processed (and invite) emails, newest first, with what became of each."""
    where = (
        "user_id = ? AND (processing_status IN ('processed', 'failed')"
        " OR (processing_status = 'skipped' AND processing_outcome = 'calendar_invite'))"
    )
    total = db.query_one(f"SELECT count(*) FROM emails WHERE {where}", (user_id,))[0]
    # Order the ids from the covering index (idx_emails_history_order), then read
    # only that page's rows: ordering whole rows read every email body.
    page = [r[0] for r in db.query(
        f"SELECT id FROM emails WHERE {where} ORDER BY date_sent IS NOT NULL, date_sent DESC, id DESC LIMIT ? OFFSET ?",
        (user_id, limit, offset),
    )]
    rows = {r["id"]: dict(r) for r in db.query(
        "SELECT id, email_provider, subject, from_email, from_name, date_sent, processing_status,"
        " processing_error, processing_outcome, processing_explanation, processed_at"
        f" FROM emails WHERE user_id = ? AND id IN ({_marks(page)})",
        (user_id, *page),
    )} if page else {}
    emails = [rows[i] for i in page if i in rows]
    by_id = {e["id"]: e for e in emails}
    for e in emails:
        e["event_sources"] = []
    if not emails:
        return [], int(total)
    sources = [dict(r) for r in db.query(
        f"SELECT s.id, s.event_id, s.source_type, s.email_id FROM event_sources s"
        f" JOIN events ev ON ev.id = s.event_id AND ev.user_id = ?"
        f" WHERE s.email_id IN ({_marks(list(by_id))}) ORDER BY s.created_at, s.id",
        (user_id, *by_id),
    )]
    event_ids = sorted({s["event_id"] for s in sources})
    events: dict[str, dict[str, Any]] = {}
    if event_ids:
        for r in db.query(
            f"SELECT id, title, review_status FROM events WHERE user_id = ? AND id IN ({_marks(event_ids)})",
            (user_id, *event_ids),
        ):
            events[r["id"]] = {"id": r["id"], "title": r["title"], "review_status": r["review_status"],
                               "event_change_proposals": [], "calendar_work_items": []}
        for p in _decode(db, "event_change_proposals", db.query(
            f"SELECT id, event_id, kind, status, change_set, resolution_reason FROM event_change_proposals"
            f" WHERE user_id = ? AND event_id IN ({_marks(event_ids)}) ORDER BY created_at, id",
            (user_id, *event_ids),
        )):
            events[p.pop("event_id")]["event_change_proposals"].append(p)
        for w in db.query(
            f"SELECT id, event_id, action, status, generation, failure_code, failure_detail FROM calendar_work_items"
            f" WHERE user_id = ? AND event_id IN ({_marks(event_ids)}) ORDER BY generation, id",
            (user_id, *event_ids),
        ):
            item = dict(w)
            events[item.pop("event_id")]["calendar_work_items"].append(item)
    for s in sources:
        by_id[s.pop("email_id")]["event_sources"].append({**s, "events": events.get(s["event_id"])})
    return emails, int(total)


def email_summary(db: Database, user_id: str, email_id: str) -> dict[str, Any] | None:
    row = db.query_one(
        "SELECT id, email_provider, subject, from_email, from_name, date_sent, snippet, has_attachments"
        " FROM emails WHERE id = ? AND user_id = ?", (email_id, user_id),
    )
    return db.schema.decode("emails", row) if row is not None else None


def email_processing_state(db: Database, user_id: str, email_id: str) -> dict[str, Any] | None:
    row = db.query_one(
        "SELECT id, processing_status, processing_error, processing_outcome, processing_explanation, processed_at"
        " FROM emails WHERE id = ? AND user_id = ?", (email_id, user_id),
    )
    return dict(row) if row is not None else None


def email_attachments(db: Database, user_id: str, email_id: str) -> list[dict[str, Any]] | None:
    """E10: None when the email is not the user's."""
    if email_summary(db, user_id, email_id) is None:
        return None
    return [dict(r) for r in db.query(
        "SELECT id, email_id, filename, mime_type, size_bytes, ingestion_status, created_at FROM attachments"
        " WHERE email_id = ? AND user_id = ? ORDER BY filename IS NULL, filename, id",
        (email_id, user_id),
    )]


def attachment_for_download(db: Database, user_id: str, attachment_id: str) -> dict[str, Any] | None:
    """E25: the owned attachment's file reference, or None."""
    row = db.query_one(
        "SELECT id, filename, mime_type, size_bytes, storage_path, ingestion_status FROM attachments"
        " WHERE id = ? AND user_id = ?", (attachment_id, user_id),
    )
    return dict(row) if row is not None else None


# --- integrations -------------------------------------------------------------


def list_integrations(db: Database, user_id: str) -> list[dict[str, Any]]:
    """E11: never any token column."""
    return _decode(db, "integrations", db.query(
        "SELECT id, user_id, provider, status, provider_email, scopes, last_sync_at, created_at, updated_at"
        " FROM integrations WHERE user_id = ? ORDER BY created_at IS NOT NULL, created_at DESC, id",
        (user_id,),
    ))


def delete_integrations(db: Database, user_id: str, integration_ids: list[str]) -> int:
    """E12: delete the user's own among ``integration_ids``; returns how many."""
    with db.write() as tx:
        cur = tx.execute(
            f"DELETE FROM integrations WHERE user_id = ? AND id IN ({_marks(integration_ids)})",
            (user_id, *integration_ids),
        )
        return cur.rowcount


# --- sender rules -------------------------------------------------------------


def list_sender_rules(db: Database, user_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in db.query(
        "SELECT id, user_id, sender_email, sender_domain, action, created_at, updated_at FROM sender_rules"
        " WHERE user_id = ? ORDER BY created_at IS NOT NULL, created_at DESC, id",
        (user_id,),
    )]


class DuplicateRule(Exception):
    pass


def create_sender_rule(
    db: Database, user_id: str, rule_id: str, sender_email: str | None, sender_domain: str | None, action: str
) -> dict[str, Any]:
    try:
        with db.write() as tx:
            tx.execute(
                "INSERT INTO sender_rules (id, user_id, sender_email, sender_domain, action, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rule_id, user_id, sender_email, sender_domain, action, tx.now_text, tx.now_text),
            )
    except UniqueViolation as exc:
        raise DuplicateRule() from exc
    row = db.query_one(
        "SELECT id, user_id, sender_email, sender_domain, action, created_at, updated_at FROM sender_rules"
        " WHERE id = ? AND user_id = ?", (rule_id, user_id),
    )
    return dict(row)  # type: ignore[arg-type]
