"""A database imported from Postgres still migrates and serves.

backend/tests/fixtures/imported_from_postgres.sql is the selko.db the one-time
importer wrote from the frozen pre-move Postgres fixture, kept after the
importer was removed (2026-11-26). Production's database was made the same
way, so every future migration must apply to this one too. The image lane
runs the same file through the real image (scripts/image-lane.sh).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from selko.db import Database, migrate
from selko.db.migrate import available, current_version
from selko.services import accounts
from selko.services.accounts import TokenKeys

DUMP = Path(__file__).resolve().parents[1] / "fixtures" / "imported_from_postgres.sql"


@pytest.fixture
def imported(tmp_path):
    path = tmp_path / "selko.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(DUMP.read_text(encoding="utf-8"))
    return path


# Validates: SEL-629
def test_the_imported_database_migrates_to_this_build(imported):
    migrate(imported)
    with sqlite3.connect(imported) as conn:
        assert current_version(conn) == max(m.version for m in available())
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    # Migrating again is a no-op.
    assert migrate(imported) == []


# Validates: SEL-629
def test_the_carried_account_signs_in_and_owns_its_events(imported):
    migrate(imported)
    db = Database(imported)
    try:
        signed = accounts.sign_in(db, TokenKeys(current="k" * 40), "fixture@example.test", "fixture-password")
        events = db.query("SELECT review_status FROM events WHERE user_id = ?", (signed.user["id"],))
    finally:
        db.close()
    statuses = {row["review_status"] for row in events}
    assert statuses == {"pending_review", "active"}, statuses


# Validates: SEL-629
def test_the_dump_is_a_real_import_not_an_empty_schema():
    text = DUMP.read_text(encoding="utf-8")
    assert "PRAGMA user_version" in text
    assert text.count("INSERT INTO") >= 10  # accounts, users, emails, events, attachments, ...
