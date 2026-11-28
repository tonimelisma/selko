# Requirements: Operations and platform

This file covers the platform Selko runs on and its invariants: the single process and data
directory, the SQLite data layer, migrations, startup, work signals and live updates, health and
metrics, error bodies, configuration, operator commands, repository guards and verification tooling.

## One process, one data directory

- **SEL-600** Selko shall run as one uvicorn process with exactly one worker
  (`selko.api.app:app --workers 1`) that serves the API, runs the background workers and serves
  the built web app from SELKO_WEB_DIR.
  unverified: fixed by the Dockerfile CMD and checked by running the image (scripts/image-check.sh);
  no test in the suites reads the CMD.
- **SEL-601** When a browser requests a page path (`/`, `/login`, `/register`, `/privacy`, `/app`,
  `/app/...`), Selko shall answer with the web app's `index.html` and `Cache-Control: no-cache`,
  while API paths such as `/events/review` are still answered by the API. [verified]
- **SEL-602** Selko shall serve hashed assets under `/_app/immutable/` with an immutable
  Cache-Control and shall never serve a file outside the web folder, including through encoded
  `..` segments. [verified]
- **SEL-603** Selko shall keep all durable state inside SELKO_DATA_DIR: the database file
  `selko.db` and the `attachments/<account-id>/` folders. [verified]
- **SEL-604** While running from the container image, Selko shall run as a non-root user and write
  only to the `/data` volume, with the root filesystem read-only.
  unverified: asserted by scripts/image-check.sh, which runs the image with `--read-only`; that
  script is not part of the pytest or web suites.

## One owner per data directory

- **SEL-605** When `selko.api` or `selko.worker_app` opens the database, Selko shall take an
  exclusive lock on `<SELKO_DATA_DIR>/.selko.lock` and hold it until the database is closed.
  [verified]
- **SEL-606** If another owner already holds the data directory lock, then Selko shall refuse to
  start with DataDirLocked naming the holder, before it creates or opens `selko.db`. [verified]
- **SEL-607** If the process holding the data directory lock dies without releasing it, then
  Selko shall let the next owner take the lock. [verified]
- **SEL-608** Selko shall let an operator command (`selko.admin`) open the database without taking
  the lock, so it runs beside a running server. [verified]

## One writer, many readers

- **SEL-609** Selko shall make every write through `Database.write()` on one writer connection
  inside `BEGIN IMMEDIATE`, so concurrent claimers never interleave and each claims a different
  row. [verified]
- **SEL-610** If a write transaction raises, then Selko shall roll back all its writes and run none
  of its after-commit callbacks. [verified]
- **SEL-611** Selko shall register the data layer's trigger functions only on the writer
  connection, so a connection outside `db.write()` that updates a triggered table fails with
  "no such function". [verified]
- **SEL-612** Selko shall give each write transaction a `tx.now` strictly greater than the previous
  transaction's, and shall set `updated_at` on changed rows to that transaction time. [verified]
- **SEL-613** Selko shall serve reads from a fixed pool of at most four (READER_POOL_SIZE)
  `query_only` reader connections, each with a 2,000 KiB page cache, whatever the number of reading
  threads. [verified]
- **SEL-614** While all four reader connections are in use, Selko shall make the next reader wait
  for one to be returned rather than open another. [verified]
- **SEL-615** If a write statement runs on a reader connection, then Selko shall refuse it.
  [verified]
- **SEL-616** Selko shall run blocking database calls from async code on a worker thread
  (`Database.run`), never on the event loop thread. [verified]
- **SEL-617** Selko shall store every timestamp as 27-character UTC text
  `YYYY-MM-DDTHH:MM:SS.ffffffZ` that sorts in time order, shall refuse a naive datetime, and every
  `strftime` column default shall produce that same format. [verified]
- **SEL-618** Selko shall write JSON as canonical text (sorted keys, no spaces, Unicode unescaped)
  and decode boolean and JSON columns to booleans and objects when reading rows. [verified]
- **SEL-619** Selko shall declare every table STRICT. [verified]
- **SEL-620** Selko shall constrain every JSON column with `CHECK(json_valid(...))`.
  unverified: present in the migration SQL; no test writes invalid JSON to prove the refusal.
- **SEL-621** If a write breaks a foreign key, a CHECK domain, a unique key, or names an unknown
  column, then Selko shall raise the matching typed error from `selko.db.errors`
  (ForeignKeyViolation, CheckViolation naming the constraint, UniqueViolation, InvalidArgument).
  [verified]
- **SEL-622** Selko shall check cross-row invariants (a pending change proposal needs an active
  event; a calendar work item's owner matches its event's owner) at commit, raising
  InvariantViolation, so the order of writes inside one transaction does not matter. [verified]
- **SEL-623** Selko shall keep the schema's enumerated CHECK domains equal to the pinned list in
  `backend/tests/schema_domains.py`, and every status literal in the data layer's SQL shall lie in
  its column's domain. [verified]

## Migrations

- **SEL-624** When the database is opened, Selko shall apply every pending migration in
  `backend/selko/db/migrations` in version order and record each version, name and SHA-256 in
  `schema_migrations`, and a second run shall apply nothing. [verified]
- **SEL-625** Before applying migration NNNN to an existing database, Selko shall write a
  consistent copy to `<data dir>/backups/pre-NNNN.db` with VACUUM INTO, and shall keep only the two
  newest `pre-NNNN.db` copies, leaving other files in that folder alone. [verified]
- **SEL-626** If a migration fails, including by leaving a foreign key violation, then Selko shall
  roll that migration back whole, leave the recorded version unchanged and delete no backup.
  [verified]
- **SEL-627** If an applied migration's file content has changed, or the database records a
  migration this build does not have, then Selko shall refuse to migrate with MigrationError.
  [verified]
- **SEL-628** Selko shall number its shipped migrations from 0001 upward without gaps. [verified]
- **SEL-629** Selko shall apply every shipped migration to the database imported from the old
  Postgres fixture (`backend/tests/fixtures/imported_from_postgres.sql`), leaving
  `integrity_check` ok, no foreign key violations, and the carried account able to sign in and
  read its events. [verified]

## Startup

- **SEL-630** When `selko.api` or `selko.worker_app` starts, Selko shall release every lease left
  by an earlier run: processing emails return to pending (or become failed with
  `lease_expired_at_limit` when attempts are exhausted), calendar work items and recoveries return
  to pending, ingestion items and attachments go to retry, sync-state leases are cleared keeping
  their generation, and running sync runs become abandoned. [verified]
- **SEL-631** When the app module is imported at startup, Selko shall not load the heavy client
  libraries (the Google API stack, PyMuPDF, anthropic, openai, google-genai); each loads on first
  use. [verified]

## Work signals and live updates

- **SEL-632** When a write that creates claimable work (a pending email, a pending ingestion item)
  commits, Selko shall wake the matching worker through WorkSignals after the commit, and if the
  write rolls back it shall send no wake-up. [verified]
- **SEL-633** If a worker's wake-up is lost, then Selko shall still claim the work on the claim
  loop's idle-backoff floor. [verified]
- **SEL-634** While the ingestion runtime is idle, Selko shall run a health-evaluation floor that
  evaluates at most once per EMAIL_HEALTH_FLOOR_SECONDS and not inside its first interval.
  [verified]
- **SEL-635** When a write commits, Selko shall publish on the in-process Bus topic `user:<id>` one
  invalidation per user, resource and operation for that transaction, never one per row.
  [verified]
- **SEL-636** If a Bus subscriber falls behind its bounded queue, then Selko shall drop that
  subscriber's oldest messages and mark it lagged; after unsubscribing it receives nothing.
  [verified]
- **SEL-637** When a signed-in user opens `GET /live` with a Bearer access token, Selko shall
  answer `text/event-stream` with a `ready` event and then an `invalidate` event carrying
  `resource` and `operation` for that user's committed writes, and never for another user's.
  [verified]
- **SEL-638** While a `/live` stream has nothing to send, Selko shall send an SSE comment
  heartbeat every HEARTBEAT_SECONDS (25 s). [verified]
- **SEL-639** When a `/live` stream's access token expires, Selko shall send a `reauth` event and
  end the stream, and when the user signs out it shall send `revoked` and end it. [verified]
- **SEL-640** If `GET /live` has no access token, then Selko shall answer 401, and if the user
  already has five open streams, then Selko shall answer 429. [verified]

## Health

- **SEL-641** Selko shall compute the work-state roll-up (`health_work_state`) as a fixed set of
  keys (HEALTH_KEYS), reporting `status` ok with zero counts on an empty database. [verified]
- **SEL-642** If an email is processing with an expired or missing lease, then Selko shall count
  it in `stale_processing_emails` and report degraded until it is no longer processing. [verified]
- **SEL-643** If a pending email has used all its attempts (`unclaimable_pending`), then Selko
  shall report degraded until the row is claimable again. [verified]
- **SEL-644** Selko shall count `failed_emails` but shall never degrade the roll-up because of
  them. [verified]
- **SEL-645** Selko shall count ready and processing emails with the worker's own claim
  predicates, so emails backing off or waiting for an attachment are not ready. [verified]
- **SEL-646** If a sync run is running without a live lease, an ingestion item or attachment is
  dead-lettered, or an incident keyed `email-sync:` (case-sensitive) is open, then Selko shall
  report degraded and return to ok once the condition clears. [verified]
- **SEL-647** If an active integration's poll is overdue by more than the warning seconds, then
  Selko shall report degraded; expired integrations and leased due integrations are not counted
  due, and future polls report zero seconds overdue. [verified]
- **SEL-648** If an eligible ingestion item (not backing off, not exhausted) has waited longer than
  the warning seconds with no live lease in flight, then Selko shall report it in
  `items_stalled_seconds`, measured from `next_retry_at` when set, and degrade until it drains.
  [verified]
- **SEL-649** Selko shall count health rows without truncation (1,500 dead letters count as
  1,500). [verified]
- **SEL-650** When `GET /health` is requested, Selko shall answer 200 with `status` ok or degraded
  from the work-state roll-up, and degraded rather than 500 when no database is open. [verified]
- **SEL-651** Selko shall publish on `/health` the build SHA from GIT_COMMIT_SHA (`build_sha`) and
  the process start time as a timezone-aware ISO-8601 `started_at`. [verified]
- **SEL-652** Selko shall publish request metrics on `/health`: `requests_per_hour`,
  `server_errors_per_hour` counting only 5xx answers, and `server_error_routes` keyed by route
  template, never by concrete path. [verified]
- **SEL-653** Selko shall publish a `memory` section on `/health` with `rss_bytes`,
  `peak_rss_bytes`, `cgroup_current_bytes`, `cgroup_limit_bytes`, `threads` and
  `reader_connections`, read from `/proc/self/status` and cgroup v2 or v1, with null where a value
  is unavailable or the cgroup has no limit. [verified]
- **SEL-654** Selko shall publish on `/health` the pending email count and oldest pending age, and
  content-free fenced-resolution gauges (conflicts per hour, retries-per-email histogram, fenced
  writes since start, conflict exhaustion count). [verified]
- **SEL-655** When `GET /health/db` is requested, Selko shall answer 200 `connected` with an open
  database and 503 without one. [verified]
- **SEL-656** When `GET /health/ingestion` is requested, Selko shall report the runtime's tasks
  (name, alive, restarts, last exception code), whether background processing is enabled, the
  in-process listener (`kind`, `bound`, `signals_sent`, `last_signal_at`) and the work-state
  counts. [verified]
- **SEL-657** While background processing is off, Selko shall report `/health/ingestion` as
  disabled with status ok, unless the work state shows lost or stale work, which degrades it.
  [verified]
- **SEL-658** If the ingestion runtime's health snapshot raises, then Selko shall answer
  `/health/ingestion` with status degraded instead of a 500. [verified]
- **SEL-659** Selko shall meter outbound bytes per destination and per bounded operation template,
  ranked by bytes, keep at most MAX_TRACKED_OPERATIONS operations per destination plus one `other`
  overflow bucket without dropping calls, and project bytes per 30 days from the observed rate.
  [verified]
- **SEL-660** Selko shall meter LLM request and response bytes under an operation named
  `<provider>:<operation>` that carries no content, and every Microsoft Graph request shall name
  an explicit operation template rather than `unknown`. [verified]
- **SEL-661** When `GET /health/egress` is requested, Selko shall report the database transport
  as `sqlite` from a real query bounded at 5 s, `unavailable` when that query fails or times out,
  and `none` without a database. [verified]
- **SEL-662** Where MEMORY_LOG_INTERVAL_SECONDS is above zero (default 60), Selko shall log a line
  `memory: rss_mb=... fds=... threads=... gc_gen2_objects=...` each interval, writing `unknown` for
  counters it cannot read, and shall start no monitor when the interval is zero or less.
  [verified]
- **SEL-663** Where MEMORY_TRACEMALLOC is true, Selko shall log the allocation growth since the
  previous interval, listing real growth sites even when larger frees fill the top of the
  comparison. [verified]
- **SEL-664** If a service's failure rate reaches the breaker threshold (default 0.5) over at
  least the minimum calls (default 5) inside the window (default 300 s), then Selko shall open
  that service's circuit breaker, half-open it after the cooldown (default 60 s), close it on a
  success and reopen it on a failure, tracking each service independently. [verified]

## Errors and configuration

- **SEL-665** Selko shall build API error bodies as exactly `{"error": <code>, "detail":
  <message>}`, with every ErrorCode constant an upper-case string equal to its name. [verified]
- **SEL-666** If an unhandled exception escapes a route, then Selko shall answer 500
  `{"error": "internal_error", "detail": "Internal server error"}` through the CORS middleware so
  the browser can read it, and log the exception.
  unverified: no test raises an unhandled exception and checks the CORS header on the 500; checked
  by reading `unhandled_exception_handler` in `backend/selko/api/app.py`.
- **SEL-667** Selko shall accept ENVIRONMENT values development, staging and production (default
  development) and refuse any other value with an error listing the valid ones. [verified]
- **SEL-668** Selko shall run background processing by default only in production, shall disable
  it when ENABLE_BACKGROUND_PROCESSING is false, and shall let a process environment variable win
  over the environment's env file. [verified]
- **SEL-669** Selko shall read ALLOWED_ORIGINS as a comma-separated list, trimming whitespace and
  ignoring empty entries, and default to the four local development origins when it is unset.
  [verified]
- **SEL-670** If neither the environment's env file nor SELKO_JWT_SECRET or SELKO_DATA_DIR is
  present, then Selko shall exit at startup with a message naming the missing file.
  unverified: no test removes all configuration and expects the exit; checked by reading
  `load_config` in `backend/selko/config.py`.
- **SEL-671** If SELKO_JWT_SECRET is shorter than 32 bytes, then Selko shall refuse to start.
  unverified: the check is in `TokenKeys` (`backend/selko/services/accounts.py`) and no test
  constructs a short key.

## Operator commands and operational records

- **SEL-672** When an operator runs `python -m selko.admin migrate`, Selko shall create or migrate
  `$SELKO_DATA_DIR/selko.db` and exit 0. [verified]
- **SEL-673** If `selko.admin seed-demo` runs without SELKO_ALLOW_DEMO_SEED=1, then Selko shall
  refuse with exit 2; with it, Selko shall seed demo data and a stored PDF attachment into an
  empty account and refuse an account that already has events. [verified]
- **SEL-674** When an LLM call is logged, Selko shall store it in `llm_call_log` for its owner with
  codec-format timestamps (`started_at` defaulting to the insert time), refuse an unknown user, and
  return it only to its owner. [verified]
- **SEL-675** When a Microsoft Graph call fails, Selko shall record it in `graph_api_failures` with
  its redacted operation, URL template, status, error code and sync run, and refuse a surface
  outside the allowed domain. [verified]
- **SEL-676** When an incident is raised for a key that is already open, Selko shall refresh its
  severity, summary and `last_seen_at` without resending the opened notification, and when it is
  raised for a resolved key, Selko shall reopen it with both notification stamps cleared.
  [verified]

## Repository guards

- **SEL-677** Selko shall contain no import of a hosted-database client (supabase, postgrest,
  asyncpg, gotrue, realtime, storage3, psycopg) in any Python file, including imports inside
  functions, and no such package in `uv.lock`. [verified]
- **SEL-678** Selko shall keep every module under `selko.services` and `selko.workers` reachable
  by import from a runtime root (`selko.api`, `selko.worker_app`, `selko.admin`), except modules
  named with an owner and reason in the test's allowlist. [verified]
- **SEL-679** Selko shall keep SQL that inserts into, updates or deletes from `events` only in the
  allowlisted data-layer modules (`db/events.py` and the named transitions). [verified]
- **SEL-680** Selko shall carry no compatibility shims ("kept for compat", "deprecated alias",
  "Legacy alias") anywhere under `backend/selko/`. [verified]
- **SEL-681** Selko shall keep the backend package's README inside the backend package directory
  so the package builds on its own. [verified]

## Verification tooling

- **SEL-682** When `scripts/verify-lanes.py` runs a lane whose input files have the same content
  fingerprint as an earlier pass, Selko shall reuse that pass, and shall run the lane again when
  any input changes; `dir/**` inputs fingerprint the files beneath. [verified]
- **SEL-683** If a lane fails, then the lane runner shall never record it as passing and shall run
  it again on the next invocation. [verified]
- **SEL-684** If a lane's declared precondition fails or one of its input patterns matches no
  file, then the lane runner shall report the lane red (BLOCKED with the remedy, or naming the
  pattern) rather than skip it, and `scripts/lanes.toml` shall declare only inputs that exist.
  [verified]
- **SEL-685** When the lane runner executes a lane, Selko shall record it in a per-run JSONL
  ledger file named by the run id, and `scripts/verify-report.py` shall summarize all ledger files.
  [verified]
- **SEL-686** Selko shall keep lane locks in one machine-wide directory shared by every worktree of
  the repository. [verified]
- **SEL-687** Selko shall release a new image on the main branch for every change to a file the
  image is built from (the Dockerfile, `.dockerignore` and what it admits), release nothing for
  changes outside those files, and run the image check on every pull request touching an image
  lane input. [verified]
- **SEL-688** Selko shall prune stored eval results only on `--apply` (dry run by default),
  keeping the current prompt hash's results and the requested number of superseded hashes.
  [verified]
- **SEL-689** Selko shall key eval inference artifacts by a content hash of operation, provider,
  model, thinking, prompt contract and fixture input (attachment bytes included, expected output
  excluded), and key scores separately so a changed expectation re-scores without re-inferring.
  [verified]
- **SEL-690** Selko shall never overwrite a completed eval inference artifact, shall let only one
  process make the provider call for a missing artifact, and shall keep replicas beside the
  canonical file. [verified]
- **SEL-691** Selko shall hash prompt and scorer source by normalized syntax, so comment and
  whitespace changes keep cached eval results while logic changes invalidate them. [verified]
