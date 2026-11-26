"""The SQLite database: one file, one writer, many readers.

Selko runs as one process, so there is exactly one writer connection and every
write goes through `Database.write()`, which holds a lock and opens
``BEGIN IMMEDIATE``. Two writers can therefore never interleave, which is what
the Postgres claim queries needed ``FOR UPDATE SKIP LOCKED`` and advisory locks
for. Readers use their own connections (one per thread) and, in WAL mode, see
the last committed state without blocking the writer.

A write transaction (`Tx`) carries what Postgres gave a transaction for free:

- ``tx.now`` -- one timestamp for the whole transaction, strictly greater
  than every earlier transaction's (Postgres ``now()``; the fingerprint fence
  relies on ``updated_at`` values never repeating);
- live hints and worker wake-ups, buffered and published only after COMMIT
  (``realtime.send`` / ``pg_notify``), de-duplicated per transaction;
- the deferred proposal invariant, checked just before COMMIT for every event
  the transaction touched.

The SQLite triggers in ``0001_initial.sql`` reach the transaction through
functions registered only on the writer connection (``selko_now``,
``selko_ts``, ``selko_emit_live``, ``selko_emit_work``, ``selko_touch_event``),
so a write from any other connection fails instead of skipping them.

Database calls are synchronous; async code runs them with `Database.run`.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from selko.db import errors
from selko.db.codec import Schema, to_timestamp, utc_now

T = TypeVar("T")

PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
)

# Page cache per connection (negative means KiB). Each connection holds its own
# copy in this process's memory, which the kernel cannot reclaim; the kernel's
# own file cache serves repeated reads just as fast and can be reclaimed under
# the container's limit. With one reader per thread and a 32 MB cache each, a
# 400 MB database took the process from 93 to 301 MiB under 40 concurrent
# requests; with 2 MB readers it stayed at 118 MiB, and no slower.
WRITER_CACHE_KIB = 16_000
READER_CACHE_KIB = 2_000
# Readers are pooled, so their total cache has a fixed bound however many
# threads FastAPI and the workers run (up to 40), rather than one per thread.
READER_POOL_SIZE = 4

# The deferred invariant Postgres enforced on event_change_proposals/events
# (enforce_event_change_proposal_invariant), checked before COMMIT.
_INVARIANT_OWNERSHIP = """
SELECT 1 FROM event_change_proposals p
JOIN events e ON e.id = p.event_id
JOIN event_sources s ON s.id = p.source_id
WHERE p.event_id = ? AND p.status = 'pending'
  AND (p.user_id IS NOT e.user_id OR s.event_id IS NOT p.event_id
       OR json_type(p.change_set) <> 'object' OR json_type(p.event_snapshot_before) <> 'object')
LIMIT 1
"""
_INVARIANT_ACTIVE = """
SELECT 1 FROM event_change_proposals p
JOIN events e ON e.id = p.event_id
WHERE p.event_id = ? AND p.status = 'pending' AND e.review_status <> 'active'
LIMIT 1
"""


def _connect(path: Path | str, cache_kib: int = WRITER_CACHE_KIB) -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(path),
        isolation_level=None,  # transactions are explicit
        check_same_thread=False,  # guarded by Database's lock / the reader pool
    )
    conn.row_factory = sqlite3.Row
    for pragma in PRAGMAS:
        conn.execute(pragma)
    conn.execute(f"PRAGMA cache_size = -{int(cache_kib)}")
    return conn


class Tx:
    """An open write transaction."""

    def __init__(self, db: Database, now: datetime) -> None:
        self.db = db
        self.conn = db._writer
        self.schema = db.schema
        self.now = now
        self.now_text: str = to_timestamp(now)  # type: ignore[assignment]
        self.live: dict[tuple[str, str], str] = {}
        self.work: set[str] = set()
        self.touched_events: set[str] = set()
        self._after_commit: list[Callable[[], None]] = []

    def ts(self, offset_seconds: float = 0) -> str:
        """``now()`` plus an offset, as stored text (Postgres ``now() + interval``)."""
        return to_timestamp(self.now + timedelta(seconds=offset_seconds))  # type: ignore[return-value]

    def execute(self, sql: str, params: Any = ()) -> sqlite3.Cursor:
        try:
            return self.conn.execute(sql, params)
        except sqlite3.Error as exc:
            raise errors.translate(exc) from exc

    def emit_live(self, user_id: str | None, resource: str, operation: str) -> None:
        # One hint per user and resource per transaction; the first operation
        # wins, as the Postgres GUC guard did.
        if user_id is not None:
            self.live.setdefault((user_id, resource), operation)

    def emit_work(self, work_type: str) -> None:
        self.work.add(work_type)

    def touch_event(self, event_id: str | None) -> None:
        if event_id is not None:
            self.touched_events.add(event_id)

    def _check_invariants(self) -> None:
        for event_id in sorted(self.touched_events):
            if self.conn.execute(_INVARIANT_OWNERSHIP, (event_id,)).fetchone():
                raise errors.InvariantViolation(
                    f"proposal ownership or payload invariant failed for event {event_id}"
                )
            if self.conn.execute(_INVARIANT_ACTIVE, (event_id,)).fetchone():
                raise errors.InvariantViolation(
                    f"pending proposal event {event_id} must have active review status"
                )

    def after_commit(self, callback: Callable[[], None]) -> None:
        self._after_commit.append(callback)


class Database:
    def __init__(self, path: Path | str, bus: Any = None, signals: Any = None) -> None:
        self.path = Path(path)
        self.bus = bus
        self.signals = signals
        self._writer = _connect(self.path)
        self._write_lock = threading.Lock()
        self._current: Tx | None = None
        self._last_now: datetime | None = None
        # Idle readers, most recently used last (LIFO keeps the warm cache busy).
        self._idle: list[sqlite3.Connection] = []
        self._readers: list[sqlite3.Connection] = []
        self._readers_cond = threading.Condition()
        self._register_functions()
        self.schema = Schema(self._writer)

    # -- the trigger functions ----------------------------------------------

    def _tx(self) -> Tx:
        if self._current is None:
            raise sqlite3.ProgrammingError("selko trigger function called outside a write transaction")
        return self._current

    def _register_functions(self) -> None:
        conn = self._writer
        conn.create_function("selko_now", 0, lambda: self._tx().now_text)
        conn.create_function("selko_ts", 1, lambda s: self._tx().ts(s))
        conn.create_function(
            "selko_emit_live", 3, lambda u, r, o: self._tx().emit_live(u, r, o)
        )
        conn.create_function("selko_emit_work", 1, lambda w: self._tx().emit_work(w))
        conn.create_function("selko_touch_event", 1, lambda e: self._tx().touch_event(e))

    # -- writing -------------------------------------------------------------

    def _next_now(self) -> datetime:
        now = utc_now()
        if self._last_now is not None and now <= self._last_now:
            now = self._last_now + timedelta(microseconds=1)
        self._last_now = now
        return now

    @contextlib.contextmanager
    def write(self) -> Iterator[Tx]:
        """The single write path: lock, BEGIN IMMEDIATE, check, COMMIT, then publish."""
        with self._write_lock:
            try:
                self._writer.execute("BEGIN IMMEDIATE")
            except sqlite3.Error as exc:
                raise errors.translate(exc) from exc
            tx = Tx(self, self._next_now())
            self._current = tx
            try:
                yield tx
                tx._check_invariants()
                self._writer.execute("COMMIT")
            except BaseException:
                self._writer.execute("ROLLBACK")
                raise
            finally:
                self._current = None
        self._publish(tx)

    # Kept for the foundation's callers; the same as write().
    transaction = write

    def _publish(self, tx: Tx) -> None:
        if self.bus is not None:
            for (user_id, resource), operation in tx.live.items():
                self.bus.publish(
                    f"user:{user_id}",
                    {"resource": resource, "operation": operation, "occurred_at": tx.now_text},
                )
        if self.signals is not None:
            for work_type in sorted(tx.work):
                self.signals.signal(work_type)
        for callback in tx._after_commit:
            callback()

    # -- reading -------------------------------------------------------------

    @contextlib.contextmanager
    def reading(self) -> Iterator[sqlite3.Connection]:
        """A read connection from the pool, for one statement or a few.

        At most READER_POOL_SIZE exist; a caller waits for a free one rather
        than opening another. Finish with the connection inside the block:
        fetch results, do not keep a cursor.
        """
        with self._readers_cond:
            while not self._idle and len(self._readers) >= READER_POOL_SIZE:
                self._readers_cond.wait()
            if self._idle:
                conn = self._idle.pop()
            else:
                conn = _connect(self.path, READER_CACHE_KIB)
                conn.execute("PRAGMA query_only = ON")
                self._readers.append(conn)
        try:
            yield conn
        finally:
            with self._readers_cond:
                self._idle.append(conn)
                self._readers_cond.notify()

    def reader_count(self) -> int:
        """Read connections open now (bounded by READER_POOL_SIZE)."""
        with self._readers_cond:
            return len(self._readers)

    def query(self, sql: str, params: Any = ()) -> list[sqlite3.Row]:
        try:
            with self.reading() as conn:
                return conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise errors.translate(exc) from exc

    def query_one(self, sql: str, params: Any = ()) -> sqlite3.Row | None:
        try:
            with self.reading() as conn:
                return conn.execute(sql, params).fetchone()
        except sqlite3.Error as exc:
            raise errors.translate(exc) from exc

    async def run(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run a synchronous database function off the event loop."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    def close(self) -> None:
        with self._readers_cond:
            for conn in self._readers:
                conn.close()
            self._readers.clear()
            self._idle.clear()
        with self._write_lock:
            self._writer.close()
