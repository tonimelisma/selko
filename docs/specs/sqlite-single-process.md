+++
spec_id = "sqlite-single-process"
readme_order = 13
title = "Single process, SQLite: the minimal Selko"
increments = "Q0–Q8"
gate = "Q0 measurements; each phase ships to the current production before the next starts"
tests = []
health = []
drills = []
+++

# Single process, SQLite: the minimal Selko

**Status:** In progress. The detailed plan is in
[`sqlite-single-process/`](sqlite-single-process/README.md): schema, every
database function, the client API and auth, the data import and cutover, and
verification, file by file. Its execution order (one branch straight to
SQLite, merged when the signed image passes its CI job) supersedes §5's
"ship each phase to today's production first"; §5's increments remain the
map of the work. The foundation (S0) is built: `backend/selko/db/`.

## 1. Target

**One process and one file.** The whole of Selko — web app, API, workers,
sign-in, live updates, attachments — runs as a single Python process (`selko`) whose state is one
SQLite database file plus one attachments directory, on one volume. A reverse
proxy in front terminates TLS. Nothing else: no Postgres, PostgREST, GoTrue,
Realtime, Storage, Kong or pooler, no Render, no hosted Supabase.

| Today | After |
|---|---|
| Hosted Supabase: Postgres, PostgREST, GoTrue, Realtime, Storage, Supavisor | `selko.db` (SQLite, WAL) + `attachments/` |
| Render: API service + web service | the same process serves the API and the static web build |
| Clients query PostgREST and GoTrue directly | clients call the API only |
| Two transports (PostgREST + asyncpg), leases fenced across processes | one in-process data layer, one writer |

## 2. Inventory (measured 2026-11-25)

**Live database schema** (local, all 120 migrations applied):

| Object | Count | Postgres-only parts |
|---|---|---|
| Tables | 30 (+1 view) | column types: 163 text, 115 `timestamptz`, 80 `uuid`, 45 integer, 23 boolean, 11 `jsonb`, 6 bigint, 5 arrays, 4 enum types, 3 numeric, 2 `time`, 1 date |
| Functions | 73 live, 2,473 lines of plpgsql; 61 `SECURITY DEFINER` | of the 73: 30 use `FOR UPDATE`, 11 `SKIP LOCKED`, 2 advisory locks, 20 `jsonb`, 19 intervals (14 `make_interval`), 10 `GET DIAGNOSTICS`, 21 `RAISE EXCEPTION`, 17 `RETURNING`, 7 `ON CONFLICT`, 5 `auth.uid()` |
| Triggers | 25 | 8 `updated_at`; 11 broadcast/notify (`realtime.send`, `pg_notify`); 6 invariants (`calendar_work_items_owner_check`, `event_change_proposals_invariant`, `events_change_proposal_invariant`, `sender_rule_before_delete`, `parse_provider_labels_trigger`, `integrations_ensure_email_sync_state`) |
| RLS policies | 44 | — |
| CHECK constraints | 52 | portable |
| Indexes | 109 (52 unique, 25 partial) | portable: SQLite has unique and partial indexes |

(The migration history holds 108 distinct function names and 53 policies;
the live counts above are what exists after later migrations replaced them.)

**Backend:** 77 modules, 26,336 lines. supabase-py: 34 files, 141 `.table(`
and 22 `.rpc(` call sites over 27 tables and 12 RPCs. asyncpg: 22 SQL
functions (`claim_*`, `complete_*`, `fail_*`, `heartbeat_email_sync`,
`save_email_with_attachment_descriptors`, …). Auth: `auth.get_user` (token
check), `auth.admin.*` in `services/users.py`. Storage: 3 calls.

**Clients:**

| Client | Supabase code | Uses |
|---|---|---|
| Web | 20 files, 3,122 lines mention Supabase | 9 tables, 2 RPCs, password sign-in/up, 1 Broadcast channel, 1 Storage download |

The web app is the only client. The native iOS and Android apps are
unmaintained (`legacy/README.md`, owner decision 2026-11-25): this plan does not
change them, and they stop working at cutover.

Client operations to serve from the API: `emails`
list/get/update; `events` list/get/update; `event_sources` list;
`attachments` list + download; `email_folders` list; `integrations`
list/delete; `integration_recoveries` list; `sender_rules`
list/create/delete; `user_calendar_settings` get/upsert; RPCs
`set_event_review_status`, `ignore_sender_and_reject_pending`. About 20
endpoints. The API's 23 existing routes are all actions; none serves these
reads today.

**Auth facts:**
- Sign-in everywhere is email + password; no social sign-in, MFA or SMS.
- GoTrue stores standard bcrypt (`$2a$10$`, checked with a throwaway local
  user, deleted afterwards), so **existing passwords carry over**: Python's
  `bcrypt` verifies them.
- No OAuth server: the MCP connector, its only user, was removed on
  2026-11-25, so Selko issues tokens to its own web app only.

**Tests:** 1,727 backend tests in 126 files; 368 integration tests in 45
files run against real Postgres. 44 of 80 unit-test files stub the Supabase
client or the pg pool; 13 frontend unit-test files stub `supabase`.

**SQLite available:** 3.53.1 in the project's Python 3.14: `RETURNING`,
`UPSERT`, `STRICT` tables, JSON/JSONB functions, partial indexes, CHECK
constraints, triggers.

## 3. Memory and size

| | Measured |
|---|---|
| API with all 5 ingestion tasks, local, idle | 148 MB |
| API in production, steady / peak | 234–294 MB (`2026-10-19-b088ca4d`) / 368 MB (`2026-10-18-dbb3c877`) |
| Of which supabase-py + asyncpg (import cost) | 14 + 4 = 18 MB, removed |
| Postgres, PostgREST, GoTrue, Realtime, Storage, Kong | 81 + 16 + 10 + 210 + 134 + 94 MB, all removed |

The single process is the API minus 18 MB plus SQLite's page cache (set to
32 MB): **about 250–380 MB at production's measured range.** It fits the
existing e2-micro VM (953 MB, of which the VM's other services use 460 MB),
with 113–243 MB headroom and the VM's swap. Run it with a 400 MB container
memory limit, so a leak kills and restarts Selko inside its own limit
instead of starving the VM. No VM resize.

Disk: the database and attachment sizes in production are not measurable
from a session (Q0).

## 4. Design

### 4.1 Process and storage

- One `uvicorn` worker. All work stays asyncio tasks in the process, as the
  ingestion runtime already is.
- `selko.db`, WAL mode, `synchronous=NORMAL`, `foreign_keys=ON`,
  `busy_timeout=5000`. One writer connection serialises every write
  (`BEGIN IMMEDIATE`); a small pool of read connections serves reads.
  Database calls run in a thread (`asyncio.to_thread`) so the event loop
  never blocks; no new dependency (`sqlite3` is in the standard library).
- `attachments/<user_id>/<attachment_id>` on the same volume; written
  atomically (temp file + rename).
- The static web build is served by the same process (`StaticFiles`, with the
  SPA's `index.html` fallback). The reverse proxy routes both `selkoapp.com`
  and `api.selkoapp.com` to it.

### 4.2 Schema

A new migration chain, `backend/selko/db/migrations/0001_initial.sql`, is
written from the **live** schema (§2), not by translating 120 migrations.
The Postgres chain is kept in git history and removed from the tree at
cutover. Versioning: `PRAGMA user_version` plus a `schema_migrations` table
recording file names and hashes.

| Postgres | SQLite |
|---|---|
| `uuid` | `TEXT` (canonical lowercase form), generated in Python |
| `timestamptz`, `date`, `time` | `TEXT`, ISO 8601, always UTC for timestamps; one codec in the data layer |
| `jsonb` | `TEXT` holding JSON, `CHECK (json_valid(col))` |
| arrays (5 columns) | JSON arrays |
| enum types (4) | `TEXT` + `CHECK (col IN (...))`, which `EXPECTED_CHECK_DOMAINS` keeps pinning |
| `numeric` (3) | `INTEGER` of the smallest unit, or `REAL` where it is a ratio |
| CHECK constraints (52), unique and partial indexes | ported as written |
| `STRICT` | every table |

### 4.3 What replaces each Postgres mechanism

| Mechanism | Replacement | Why it is enough |
|---|---|---|
| `FOR UPDATE … SKIP LOCKED` claims (11 functions), advisory locks (2) | `UPDATE … WHERE id = (SELECT … LIMIT 1) RETURNING *` inside `BEGIN IMMEDIATE` | there is one writer; two claimers can't interleave |
| Leases, `lock_generation` fencing | **kept** as columns and checks | in-process asyncio tasks still overlap; the existing fencing tests keep proving it |
| Crash recovery of `processing` rows | at startup, before any task starts: every lease is expired (one process: any lease at startup belongs to a dead run) | deterministic, replaces lease-expiry waiting |
| plpgsql functions (73) | Python functions in one `selko/db/` package, one per current function, same name, same contract, each inside one transaction | "one implementation per operation" holds; names stay greppable |
| `RAISE EXCEPTION` invariants, the 6 invariant triggers | checks in those Python functions; the simple ones (`updated_at`, owner checks) as SQLite triggers (`RAISE(ABORT, …)`) | SQLite triggers cover row-local rules |
| `pg_notify` work wake-ups, `realtime.send` broadcasts (11 triggers) | an in-process event bus, published by the data layer **after commit** | there is no other process to notify |
| RLS (44 policies) | every client endpoint takes the user from the verified token and every query in `selko/db/` takes `user_id`; no query function without it | enforced by a test (Q3) |
| `SECURITY DEFINER` (61) | gone: there is no database role boundary any more | the API is the only door |
| `auth.uid()` | the token's subject, passed explicitly | — |

### 4.4 Auth (replaces GoTrue)

- `accounts` table: id (the existing `auth.users.id`, so every foreign key
  survives), email, bcrypt hash, timestamps.
- `POST /auth/signup`, `POST /auth/token` (password and refresh grants),
  `POST /auth/logout`, `GET /auth/user`. Access tokens: JWT, HS256 with a
  server secret from the secrets file, 1 hour (today's `jwt_expiry`).
  Refresh tokens: random, stored hashed, rotated on use, 10-second reuse
  window (today's settings). Sign-in rate limits through the existing
  `slowapi` limiter.

### 4.5 Live updates (replaces Realtime)

`GET /live`: server-sent events, one stream per signed-in client, carrying
the same `{resource, operation, entity_id, occurred_at}` invalidation hints
from the event bus, filtered to the caller. The browser's `EventSource`
cannot send an `Authorization` header, so the web client uses a streaming
`fetch`. The client keeps catching up from the API on (re)connect, as they already do.

### 4.6 Deploy

- `Dockerfile`: Python 3.14, `uv sync --frozen`, the built web app,
  non-root, read-only root, `/data` the only writable volume.
- CI builds and cosign-signs `ghcr.io/tonimelisma/selko:<sha>` keylessly.
  `deploy-production` keeps the owner's yes per SHA: it moves `:latest` to
  the approved, signed `<sha>`. The server pulls signed images itself and
  rolls back if `/health` does not serve the new SHA.
- **Migrations at startup**, before serving: if any are pending, first
  `VACUUM INTO /data/pre-<sha>.db` (a consistent copy; seconds at small
  size), then apply each in its own transaction. Failure: the transaction
  rolls back, the process exits, the old image comes back unchanged.
  Rolling back an image after a migration that succeeded restores
  `pre-<sha>.db`; writes since the deploy are lost, which bounds a rollback
  to the minutes between deploy and decision.
- `/health` publishes the schema version; the `schema-compat` lane lists repo
  migrations newer than it (what `supabase db push --dry-run` reported).
- Backups: the server's disk snapshots. WAL mode commits atomically, so a
  snapshot restores like a power cut, which SQLite recovers from.

### 4.7 What gets simpler

- **The test database is the production database engine.** Integration
  tests open a temp SQLite file: no Docker, no `supabase start`, no local
  vs. hosted gap (local Supabase never had Supavisor; that whole class of
  Tier 2-only failures disappears).
- One transport; no PostgREST select strings to pin against a live schema;
  no egress to a database host (Supabase was 18,369 of 27,412 counted calls
  in `2026-08-23-15a813b3`).
- Two processors fewer in the privacy policy (Supabase, Render).

### 4.8 What gets worse

- One process: an API crash stops workers and web at once (restart takes
  seconds; leases are reset at startup).
- No hosted staging. The Q4 lane, which boots the production image, is the
  substitute.
- Up to 24 hours of data loss on a disk-snapshot restore; no point-in-time
  recovery.
- The legacy iOS/Android apps stop working at cutover; web users sign in
  again (passwords still work).

## 5. Increments

Order matters: **every phase until Q7 ships to today's production
(Render + hosted Supabase) and is verified there**, so the final swap
touches only the backend's data layer.

| # | Increment | Done when |
|---|---|---|
| Q0 | Measure production: database size per table, attachment count and bytes, user count, whether sign-up requires email confirmation (if yes, signup sends mail through Resend, which the API already uses) | numbers recorded in this spec |
| Q1 | **Client data through the API.** ~20 endpoints (§2) on today's database; the web app switches to them; PostgREST no longer called by any client | `test_frontend_select_columns_exist_in_the_live_schema` has nothing left to check and is deleted; a test proves no client source calls `.from(` |
| Q2 | **Live updates through the API.** `/live` fed by today's `pg_notify`; the web app switches; `realtime.send` triggers removed | Realtime unused in production for 7 days |
| Q3 | **Ownership without RLS.** Every client endpoint scoped by the token's user; a generated test calls every endpoint as user B with user A's ids and requires 404 | the cross-user test covers every route (it fails when a route is added without it) |
| Q4 | **Image, signing, startup migrations, production-image lane** (§4.6) | lane boots the image and runs the smoke and sign-in tests |
| Q5 | **Own auth on today's database.** `accounts` filled from `auth.users` (bcrypt hashes copied), `/auth/*`; the web app switches; GoTrue unused | sign-in with an existing password works in the web app |
| Q6 | **The SQLite data layer** (the big one): `selko/db/` with the 73 functions and 22 asyncpg operations as Python, `0001_initial.sql`, attachments on disk; supabase-py and asyncpg removed; the 368 integration tests and the 44 stubbing unit-test files moved to a temp SQLite file | full backend suite green on SQLite; `test_no_worker_module_retains_a_postgrest_fallback` replaced by a test that `supabase` and `asyncpg` are not importable from `selko` |
| Q7 | **Cutover** (owner's explicit yes): stop writes on Render; a one-shot `selko import-from-postgres` inside the signed image, run on the server, reads production through the read-only URL and writes `selko.db`, copies attachment objects to `attachments/`, and compares row counts and per-table checksums; start; switch DNS for `selkoapp.com` and `api.selkoapp.com`; deploy log T+0/T+15m/T+24h | health invariants green; counts match |
| Q8 | **Retire** Render services and the Supabase project after 14 days untouched (the way back); remove `supabase/`, the Supabase CLI from setup and CI, and the PostgREST/asyncpg rules from CLAUDE.md | — |

The import (Q7) runs on the server, not in Actions: this repository is
public, and a workflow artifact holding user data would be readable by
anyone.

## 6. Found while measuring

`uv run python -m selko.api` (CLAUDE.md, Essential Commands) crashes:
`setup_logging() got an unexpected keyword argument 'level'`
(`backend/selko/api/__main__.py:12`). `uvicorn selko.api.app:app` works.
