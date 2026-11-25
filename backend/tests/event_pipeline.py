"""Helpers for tests of the event pipeline (`selko.services.events`) on a real database.

The database is never stubbed. What stays mocked is what leaves the process:
the LLM (`event_processing.extract_calendar_events`, `compare_events`,
`propose_event_update`) and the calendar providers' HTTP reads
(`calendars.fetch_calendar_events_for_date_range`, `get_calendar_event`, ...).

`spy_commit` wraps the real `commit_email_extraction` so a test can assert on
the decisions the producer built *and* on the rows the commit wrote.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from selko.db import events as db_events
from selko.db.codec import new_id

WORKER = "worker-test"
GENERATION = 1


def claimed_email(factory, user_id: str, *, worker: str = WORKER, generation: int = GENERATION,
                  **extra: Any) -> str:
    """An email the extraction worker holds, as `claim_unprocessed_email` leaves it."""
    return factory.email(
        user_id, processing_status="processing", locked_by=worker,
        locked_until="2099-01-01T00:00:00.000000Z", lock_generation=generation, **extra,
    )


def email_row(db, email_id: str) -> dict[str, Any]:
    return db.schema.decode("emails", db.query_one("SELECT * FROM emails WHERE id = ?", (email_id,)))


def lease(db, email_id: str) -> dict[str, Any]:
    """The keyword arguments `save_extracted_events` needs to commit under the email's lease."""
    row = email_row(db, email_id)
    return {"locked_by": row["locked_by"], "lock_generation": row["lock_generation"]}


def gateway() -> MagicMock:
    gw = MagicMock()
    gw.for_user.return_value = gw
    gw.for_email.return_value = gw
    return gw


def iso(value: datetime) -> str:
    """Stored text for an aware datetime."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def future_local(days: int = 30, hour: int = 14) -> datetime:
    """A naive wall-clock time ``days`` ahead (the LLM's civil-time shape)."""
    future = datetime.now() + timedelta(days=days)
    return future.replace(hour=hour, minute=0, second=0, microsecond=0)


def event_at(factory, user_id: str, start: datetime, *, hours: int = 1, **extra: Any) -> str:
    """An event at the naive local ``start`` in ``America/New_York`` (the default zone)."""
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/New_York")
    aware = start.replace(tzinfo=zone)
    values = {"title": "Team Meeting", "location": "Room A", "description": "Weekly sync"}
    values.update(extra)
    return factory.event(
        user_id, start_datetime=iso(aware), end_datetime=iso(aware + timedelta(hours=hours)), **values
    )


def ical_uid(factory, user_id: str, email_id: str, uid_hash: str, *, event_id: str | None = None,
             method: str = "REQUEST", sequence: int = 0) -> None:
    """The email carries a calendar component with ``uid_hash``; ``event_id`` already holds it."""
    factory._insert("email_calendar_components", {
        "id": new_id(), "email_id": email_id, "user_id": user_id, "component_index": 0,
        "method": method, "uid_hash": uid_hash, "recurrence_id": "", "sequence": sequence,
    })
    if event_id is not None:
        factory._insert("event_identity_hints", {
            "id": new_id(), "user_id": user_id, "event_id": event_id, "kind": "ical_uid",
            "value_hash": uid_hash, "recurrence_id": "", "strength": "authoritative",
            "sequence": sequence,
        })


def stored_attachment(db, factory, user_id: str, email_id: str, data: bytes, *,
                      filename: str, mime_type: str) -> str:
    """An attachment row whose bytes are on disk under the data directory."""
    from selko.db.runtime import ATTACHMENTS_DIR

    storage_path = f"{user_id}/{new_id()[:12]}_{filename}"
    path = db.path.parent / ATTACHMENTS_DIR / storage_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return factory._insert("attachments", {
        "id": new_id(), "user_id": user_id, "email_id": email_id, "filename": filename,
        "mime_type": mime_type, "size_bytes": len(data), "storage_path": storage_path,
        "ingestion_status": "stored",
    })


class CommitSpy:
    """Records every decision list passed to the real commit."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, Any]]] = []
        self.results: list[dict[str, Any]] = []

    @property
    def decisions(self) -> list[dict[str, Any]]:
        return [d for call in self.calls for d in call]


@pytest.fixture
def spy_commit(monkeypatch) -> CommitSpy:
    spy = CommitSpy()
    real = db_events.commit_email_extraction

    def wrapper(db, email_id, worker_id, generation, decisions, terminal):
        spy.calls.append(list(decisions))
        result = real(db, email_id, worker_id, generation, decisions, terminal)
        spy.results.append(result)
        return result

    monkeypatch.setattr("selko.services.events.db_events.commit_email_extraction", wrapper)
    return spy


@contextlib.contextmanager
def providers_offline(calendar_events: list[dict[str, Any]] | None = None) -> Iterator[MagicMock]:
    """The calendar provider's live read returns ``calendar_events`` (default none)."""
    with patch(
        "selko.services.events.calendars.fetch_calendar_events_for_date_range",
        return_value=list(calendar_events or []),
    ) as read:
        yield read


__all__ = [
    "CommitSpy", "GENERATION", "WORKER", "claimed_email", "email_row", "event_at", "future_local",
    "gateway", "ical_uid", "stored_attachment",
    "iso", "lease", "providers_offline", "spy_commit",
]
