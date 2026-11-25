"""The process's one database, opened at startup.

`open_database` migrates the file first, then opens it with the event bus and
the worker signals attached. Everything else asks `get_database()`; tests use
`use_database` to install their own.
"""

from __future__ import annotations

import logging
from pathlib import Path

from selko.db import datalock
from selko.db.bus import Bus, WorkSignals
from selko.db.connection import Database
from selko.db.migrate import migrate

logger = logging.getLogger(__name__)

DATABASE_FILE = "selko.db"
ATTACHMENTS_DIR = "attachments"

_database: Database | None = None
_lock = None


def open_database(data_dir: Path | str, *, owner: str | None = None) -> Database:
    """Migrate and open ``<data_dir>/selko.db``; idempotent within a process.

    ``owner`` names a server process (``selko.api``, ``selko.worker_app``): it
    takes the directory's lock first (selko.db.datalock) and raises
    ``DataDirLocked`` if another process holds it. Operator commands pass none.
    """
    global _database, _lock
    data_dir = Path(data_dir)
    path = data_dir / DATABASE_FILE
    if _database is not None and _database.path == path:
        return _database
    data_dir.mkdir(parents=True, exist_ok=True)
    if owner is not None:
        _lock = datalock.acquire(data_dir, owner)
    (data_dir / ATTACHMENTS_DIR).mkdir(exist_ok=True)
    applied = migrate(path)
    if applied:
        logger.info("database migrated: %s", ", ".join(applied))
    _database = Database(path, bus=Bus(), signals=WorkSignals())
    return _database


def get_database() -> Database:
    if _database is None:
        raise RuntimeError("the database is not open (selko.db.runtime.open_database runs at startup)")
    return _database


def use_database(database: Database | None) -> None:
    """Install (or clear) the process database; for tests and tools."""
    global _database
    _database = database


def attachments_dir() -> Path:
    return get_database().path.parent / ATTACHMENTS_DIR


def close_database() -> None:
    global _database, _lock
    if _database is not None:
        _database.close()
        _database = None
    datalock.release(_lock)
    _lock = None
