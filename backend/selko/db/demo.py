"""Demo data for an account: one email, its attachment, one event awaiting review.

Used by the image's CI job to exercise review, live updates and attachment
download without Gmail or an LLM. Refuses an account that already has events,
so it can never mix into real data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from selko.db.codec import new_id
from selko.db.connection import Database
from selko.db.errors import InvalidArgument, NotFound

ATTACHMENT_BYTES = b"%PDF-1.4\n% Selko demo ticket\n"


def seed_demo(db: Database, email: str, attachments_dir: Path) -> dict[str, Any]:
    account = db.query_one("SELECT id FROM accounts WHERE email = ?", (email.strip().lower(),))
    if account is None:
        raise NotFound(f"no account for {email}")
    user_id = account["id"]
    if db.query_one("SELECT count(*) FROM events WHERE user_id = ?", (user_id,))[0]:
        raise InvalidArgument("the account already has events; demo data is only for an empty account")
    email_id, event_id, source_id, attachment_id = new_id(), new_id(), new_id(), new_id()
    storage_path = f"{user_id}/{attachment_id}/ticket.pdf"
    target = attachments_dir / storage_path
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".tmp")
    temp.write_bytes(ATTACHMENT_BYTES)
    temp.replace(target)
    with db.write() as tx:
        start = tx.ts(7 * 86400)
        tx.execute(
            "INSERT INTO emails (id, user_id, provider_message_id, subject, from_email, from_name, date_sent,"
            " snippet, has_attachments, processing_status, processed_at, processing_outcome, created_at)"
            " VALUES (?, ?, ?, 'Your concert tickets', 'tickets@example.test', 'Example Tickets', ?,"
            " 'Doors open at 7pm', 1, 'processed', ?, 'event_created', ?)",
            (email_id, user_id, f"demo-{email_id}", tx.now_text, tx.now_text, tx.now_text),
        )
        tx.execute(
            "INSERT INTO attachments (id, user_id, email_id, filename, mime_type, size_bytes, storage_path,"
            " ingestion_status, created_at) VALUES (?, ?, ?, 'ticket.pdf', 'application/pdf', ?, ?, 'stored', ?)",
            (attachment_id, user_id, email_id, len(ATTACHMENT_BYTES), storage_path, tx.now_text),
        )
        tx.execute(
            "INSERT INTO events (id, user_id, title, start_datetime, end_datetime, location, review_status,"
            " created_at, updated_at) VALUES (?, ?, 'Concert', ?, ?, 'Example Hall', 'pending_review', ?, ?)",
            (event_id, user_id, start, tx.ts(7 * 86400 + 7200), tx.now_text, tx.now_text),
        )
        tx.execute(
            "INSERT INTO event_sources (id, event_id, email_id, source_origin, extracted_data, created_at)"
            " VALUES (?, ?, ?, 'email', '{}', ?)",
            (source_id, event_id, email_id, tx.now_text),
        )
    return {"user_id": user_id, "email_id": email_id, "event_id": event_id, "attachment_id": attachment_id}
