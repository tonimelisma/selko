"""Shared fixtures for tests of the SQLite data layer (`selko.db`).

Every test gets a fresh database file with all migrations applied, a `Bus` and
`WorkSignals` attached, and small factories that insert valid rows through a
write transaction. Factories take explicit ids so assertions can name rows.

    def test_something(db, factory):
        user = factory.user()
        event = factory.event(user)
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from selko.db import Database, migrate
from selko.db.bus import Bus, WorkSignals
from selko.db.codec import new_id, to_json


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    path = tmp_path / "selko.db"
    migrate(path)
    database = Database(path, bus=Bus(), signals=WorkSignals())
    yield database
    database.close()


class Factory:
    """Insert minimal valid rows. Each returns the new row's id."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._n = itertools.count(1)

    def _insert(self, table: str, values: dict[str, Any]) -> str:
        values = self.db.schema.encode(table, values)
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        with self.db.write() as tx:
            tx.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(values.values()))
        return values["id"] if "id" in values else values.get("integration_id")  # type: ignore[return-value]

    def user(self, user_id: str | None = None, email: str | None = None) -> str:
        user_id = user_id or new_id()
        email = email or f"user{next(self._n)}@example.test"
        with self.db.write() as tx:
            tx.execute(
                "INSERT INTO accounts (id, email, password_hash, created_at, updated_at) VALUES (?, ?, 'x', ?, ?)",
                (user_id, email, tx.now_text, tx.now_text),
            )
            tx.execute("INSERT INTO users (id, email) VALUES (?, ?)", (user_id, email))
        return user_id

    def integration(self, user_id: str, provider: str = "gmail", status: str = "active", **extra: Any) -> str:
        return self._insert(
            "integrations",
            {"id": new_id(), "user_id": user_id, "provider": provider, "status": status,
             "access_token": "test-access-token", **extra},
        )

    def email(self, user_id: str, **extra: Any) -> str:
        return self._insert(
            "emails",
            {"id": new_id(), "user_id": user_id, "provider_message_id": f"msg-{next(self._n)}",
             "subject": "Subject", **extra},
        )

    def event(self, user_id: str, review_status: str = "pending_review", **extra: Any) -> str:
        values = {"id": new_id(), "user_id": user_id, "title": "Event",
                  "start_datetime": "2026-12-01T17:00:00.000000Z", "review_status": review_status}
        values.update(extra)
        return self._insert("events", values)

    def event_source(self, event_id: str, email_id: str | None = None, **extra: Any) -> str:
        values: dict[str, Any] = {"id": new_id(), "event_id": event_id, "extracted_data": {}}
        if email_id is not None:
            values.update(source_origin="email", email_id=email_id)
        else:
            values.update(source_origin="google_calendar", google_calendar_source_event_id=f"g-{next(self._n)}")
        values.update(extra)
        return self._insert("event_sources", values)

    def row(self, table: str, row_id: str) -> dict[str, Any] | None:
        found = self.db.query_one(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
        return self.db.schema.decode(table, found)


@pytest.fixture
def factory(db: Database) -> Factory:
    return Factory(db)


__all__ = ["Factory", "db", "factory", "new_id", "to_json"]
