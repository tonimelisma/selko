---
paths:
  - "backend/**"
---

# Backend conventions

The architecture principles every backend change keeps. Each is decided in an ADR; the design
docs carry the detail ([data layer](../../docs/design/data-layer.md),
[event lifecycle](../../docs/design/event-lifecycle.md), [workers](../../docs/design/workers.md)).

- **One process, one data directory.** The image runs one uvicorn worker that serves the built web
  app, the API and the background workers; all state is in `SELKO_DATA_DIR` (`selko.db`,
  `attachments/`). The root filesystem is never written.
- **One owner per data directory.** `selko.api` and `selko.worker_app` hold an exclusive `flock` on
  `<SELKO_DATA_DIR>/.selko.lock` (`selko.db.datalock`); `selko.admin` takes none.
- **One writer, many readers.** Every write is a `db.write()` transaction (`BEGIN IMMEDIATE`) with
  one strictly increasing `tx.now`; reads use the four-reader pool (`Database.reading()`). Never
  hold a transaction across LLM or provider I/O. Timestamps are fixed-width
  `YYYY-MM-DDTHH:MM:SS.ffffffZ` text; tables are `STRICT`; JSON columns are
  `CHECK (json_valid(...))`.
- **Migrations** live in `backend/selko/db/migrations/` and apply at startup with a hash-checked
  ledger and a `VACUUM INTO` backup before each. A migration is done when a test has exercised what
  it adds against a real file; one that touches a populated table also runs on the imported fixture
  (`backend/tests/fixtures/imported_from_postgres.sql`).
- **Typed errors, not driver errors**: catch `selko.db.errors` (`NotFound`, `NotOwned`,
  `UniqueViolation`, `DbBusy`, …).
- **Ownership is the `user_id` argument** of every public `selko.db` function that touches a
  user-owned table (`backend/tests/db/test_ownership.py`); a route answers another user's row with
  404, never 403.
- **One implementation per operation.** Never write a second path for the same operation; events
  are written only by the fenced `selko.db.events.commit_email_extraction`
  (`backend/tests/test_single_data_layer.py`). Every module under `backend/selko/` is reachable
  from `selko.api`, `selko.worker_app` or `selko.admin` (`backend/tests/test_reachability.py`).
- **Never narrow a CHECK constraint without checking its writers**: domains are pinned in
  `backend/tests/schema_domains.py`.
- **Work arrives by signal, not by polling.** A write that creates work calls `tx.emit_work(...)`;
  a change a user should see calls `tx.emit_live(user, resource)`. The safety-net poll is a floor,
  not a schedule; a new unconditional periodic call is justified in the PR body.
- **Every outbound byte is attributed** (`selko.services.egress`, bounded operation templates).
- **Every extraction decision states its `intent`** and, except `record_only`, its
  `fields.review_status`; declined events are terminal except the `booking_confirmed` reopen.
- **Workers are the only calendar writers.** API requests enqueue `calendar_work_items`; queueing
  never writes `events.review_status`. Never mark the Outlook integration expired from a calendar
  failure: that row also carries mail.
- **Heavy client libraries load on first use** (`backend/tests/test_startup_footprint.py`), and log
  lines carry ids, never email content (`backend/tests/test_logging.py`).
- **Health signals must be able to return to green.** Before adding one, say what makes it go back
  to green and whether the system does that on its own.
- **An unhandled exception still returns a CORS-bearing 500** (the catch-all handler in
  `backend/selko/api/app.py`).
- **A client request is schema, not text.** The web app reads through
  `backend/selko/api/routes/client.py`, tested over a real database in
  `backend/tests/db/test_client_routes.py`; a field a page reads that no route test returns is
  untested.
