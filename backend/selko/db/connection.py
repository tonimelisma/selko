"""The SQLite database: one file, one writer, many readers.

Selko runs as one process, so there is exactly one writer connection and every
write goes through `Database.transaction()`, which holds a lock and opens
``BEGIN IMMEDIATE``. Two writers can therefore never interleave, which is what
the Postgres claim queries needed ``FOR UPDATE SKIP LOCKED`` and advisory locks
for. Readers use their own connections (one per thread) and, in WAL mode, see
the last committed state without blocking the writer.

Database calls are synchronous; async code runs them with `Database.run`, which
moves them to a worker thread so the event loop never waits on disk.

`after_commit` callbacks run only once the transaction has committed: that is
where the data layer publishes the events Postgres used to send with
``pg_notify`` and ``realtime.send``. A rolled-back transaction publishes nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, TypeVar

from selko.db.codec import Schema

T = TypeVar("T")

PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
    # Negative means KiB: a 32 MB page cache per connection at most.
    "PRAGMA cache_size = -32000",
)


def _connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(path),
        isolation_level=None,  # transactions are explicit
        check_same_thread=False,  # guarded by Database's lock / thread-local use
    )
    conn.row_factory = sqlite3.Row
    for pragma in PRAGMAS:
        conn.execute(pragma)
    return conn


class Transaction:
    """An open write transaction: the connection plus its after-commit callbacks."""

    def __init__(self, conn: sqlite3.Connection, schema: Schema) -> None:
        self.conn = conn
        self.schema = schema
        self._after_commit: list[Callable[[], None]] = []

    def execute(self, sql: str, params: Any = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def after_commit(self, callback: Callable[[], None]) -> None:
        self._after_commit.append(callback)


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._writer = _connect(self.path)
        self._write_lock = threading.Lock()
        self._local = threading.local()
        self._readers: list[sqlite3.Connection] = []
        self._readers_lock = threading.Lock()
        self.schema = Schema(self._writer)

    def reload_schema(self) -> None:
        """Re-read column kinds after a migration changed the tables."""
        self.schema = Schema(self._writer)

    @contextlib.contextmanager
    def transaction(self) -> Iterator[Transaction]:
        """The single write path: lock, BEGIN IMMEDIATE, commit or roll back, then callbacks."""
        with self._write_lock:
            tx = Transaction(self._writer, self.schema)
            self._writer.execute("BEGIN IMMEDIATE")
            try:
                yield tx
            except BaseException:
                self._writer.execute("ROLLBACK")
                raise
            self._writer.execute("COMMIT")
        for callback in tx._after_commit:
            callback()

    def reader(self) -> sqlite3.Connection:
        """This thread's read connection (created on first use)."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = _connect(self.path)
            conn.execute("PRAGMA query_only = ON")
            self._local.conn = conn
            with self._readers_lock:
                self._readers.append(conn)
        return conn

    async def run(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run a synchronous database function off the event loop."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    def close(self) -> None:
        with self._readers_lock:
            for conn in self._readers:
                conn.close()
            self._readers.clear()
        with self._write_lock:
            self._writer.close()
