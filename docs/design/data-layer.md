GOVERNS: backend/selko/db/**

# Data layer

`backend/selko/db/` is the only code that reads or writes `selko.db`. Decisions:
[ADR 0001](../adr/0001-one-process-one-sqlite-file.md),
[ADR 0003](../adr/0003-one-writer-many-readers.md),
[ADR 0016](../adr/0016-ownership-by-user-id-in-the-data-layer.md). Tables and columns:
[database schema](database-schema.md). Requirements: [operations](../requirements/operations.md).

## Connections and transactions

- One writer connection behind a lock; every write is `db.write()`, a `BEGIN IMMEDIATE`
  transaction. Two writers never interleave, so claims are a plain
  `UPDATE … WHERE id = (SELECT … LIMIT 1) RETURNING *`. Leases and generations stay, because
  in-process tasks still overlap.
- Readers: a fixed pool of four `query_only` WAL connections (`Database.reading()`), 2 MB page
  cache each; the writer has a 16 MB cache. A 32 MB cache per thread-reader took the process from
  93 to 301 MiB under 40 concurrent requests; the pool stayed near 118 MiB with no slowdown.
- PRAGMAs: WAL, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`. Blocking calls run
  in a thread (`Database.run`).
- `tx.now` is one timestamp per transaction, strictly increasing across transactions. The
  `updated_at` fingerprint fences depend on values never repeating.
- Never hold a transaction across LLM or provider I/O.

## After-commit signals

Live hints (`tx.emit_live`) and work wake-ups (`tx.emit_work`) are buffered, de-duplicated per
transaction, published only after COMMIT and dropped on rollback. Triggers reach them through
functions registered only on the writer connection, so a write from any other connection fails
instead of bypassing the bus ([ADR 0008](../adr/0008-work-arrives-by-signal.md)).

## Ownership and invariants

- Every public function that touches a user-owned table takes `user_id` first; worker-wide
  functions are listed in `WORKER_SCOPED` with a reason (`backend/tests/db/test_ownership.py`).
- Deferred invariants (a pending proposal needs an active event, …) are a pre-commit check over
  the event ids the transaction touched; only `db/proposals.py` and `db/events.py` write those
  tables.
- Errors are typed (`selko.db.errors`: `NotFound`, `NotOwned`, `InvalidArgument`,
  `UniqueViolation`, `CheckViolation`, `ForeignKeyViolation`, `NotNullViolation`, `DbBusy`, the
  proposal-state errors). Services and routes catch those, never driver errors. Mapping the
  proposal-state errors and `DbBusy` to 409/503 is open (#453).

## Schema conventions

uuid → lowercase TEXT; timestamps → fixed-width UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ` text (text order
is time order); JSON → TEXT with `CHECK (json_valid(...))`; arrays → JSON arrays; enums → TEXT with
a CHECK domain pinned in `backend/tests/schema_domains.py`; booleans → INTEGER 0/1; every table
`STRICT`; one codec (`selko.db.codec`). A schema object and the code that fills it land in the same
change.

## Startup and migrations

- Before any worker starts, every lease is released and `running` sync runs become `abandoned`:
  with one owner per data directory ([ADR 0002](../adr/0002-one-owner-per-data-directory.md)), any
  lease at startup belongs to a dead run. Generations are never reset.
- Migrations (`backend/selko/db/migrations/NNNN_name.sql`) apply at startup through
  `selko.db.migrate`: `PRAGMA user_version` plus a hash-checked ledger; a `VACUUM INTO
  backups/pre-NNNN.db` copy before pending migrations, keeping the two newest (about 300 MB each in
  production); each migration in its own transaction with foreign keys checked before commit. On
  failure the process exits and the previous image comes back; rolling back after a successful
  migration means restoring the copy, losing writes since the deploy.
- SQL that has never been executed has not been tested: every database test runs on a real
  migrated file, and a migration is done when a test exercised what it adds.
