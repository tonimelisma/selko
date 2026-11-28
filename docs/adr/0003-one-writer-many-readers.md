# 0003. One writer connection, a small pool of WAL readers

- Status: accepted
- Date: 2026-11-28

## Context and problem

SQLite allows one writer at a time. In-process tasks (requests, ingestion, extraction, calendar
workers) still overlap, so leases and generations are kept, but writes must never interleave.
Memory is limited (the container gets 400 MB). Requirements:
[SEL-609..623](../requirements/operations.md).

## Decision drivers

- No interleaved writes, no `database is locked` surprises.
- Bounded memory under load.
- Claims are simple: `UPDATE … WHERE id = (SELECT … LIMIT 1) RETURNING *` under the writer.

## Considered options

### One writer behind a lock with `BEGIN IMMEDIATE`, four pooled `query_only` WAL readers with a 2 MB page cache each (chosen)

- Good: writes are serialized by construction; the kernel's file cache serves reads as fast.
- Bad: a long write blocks other writes.
- Failure modes: a writer held across network I/O would stall the system, so transactions never span LLM or provider calls.

### One reader connection per thread with a 32 MB cache each

- Good: no pool to size.
- Bad: measured: a 400 MB database's process went from 93 to 301 MiB under 40 concurrent requests.
- Failure modes: out-of-memory kills under load.

## Decision

`selko.db.Database` keeps one writer connection; every write is a `db.write()` transaction with
`BEGIN IMMEDIATE`. `tx.now` is one strictly increasing UTC timestamp per transaction, stored as
fixed-width `YYYY-MM-DDTHH:MM:SS.ffffffZ` text. Tables are `STRICT`, JSON columns
`CHECK (json_valid(...))`. Reads use a fixed pool of four reader connections (`Database.reading()`).
SQLite failures surface as typed errors from `selko.db.errors` (`NotFound`, `NotOwned`,
`UniqueViolation`, `DbBusy`, …); services and routes catch those, never driver errors.

## Consequences

The pooled readers held the measured process near 118 MiB with no slowdown. `/health` →
`memory` reports RSS, the cgroup limit, threads and open readers, so a regression is visible.

## Confirmation

`backend/tests/test_sqlite_foundation.py` and the data-layer tests tagged SEL-609..623;
`backend/tests/test_sqlite_schema.py` (STRICT, pinned CHECK domains).

## Retirement proof

A measured write-contention problem that batching cannot fix.

## Reversal plan

Change the pool size or cache in `selko.db.connection`; the writer model itself is load-bearing
for every lease and fence and would need a new concurrency design.
