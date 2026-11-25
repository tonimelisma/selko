# Single process, SQLite: the detailed migration plan

The overview and the reasons are in [`../sqlite-single-process.md`](../sqlite-single-process.md).
This folder is the detailed plan: what changes, file by file and function by
function, how it is verified, and how production moves. Written 2026-11-25 from
the code and the local database; every claim cites a file and line or a
measurement, and anything that could not be measured is marked `UNKNOWN`.

## The end state (the acceptance test)

`ghcr.io/tonimelisma/selko:<sha>`, cosign-signed by this repository's CI on
`main`: one non-root process serving the web app, the API and the workers on
one port, with all state in `/data` (`selko.db` plus attachments) and its
configuration from an env file. It is done when a CI job runs that exact image
with a read-only root, no capabilities, a 400 MB memory limit and `/data` as
the only volume, and passes:

| Check | Where it is specified |
|---|---|
| `/health` green | [05 §C.9](05-verification.md), [04 §C.1](04-data-cutover.md) |
| sign-up and sign-in | [03 §B](03-api-auth-web.md), [05 §B.8](05-verification.md) |
| review an event | [03 §A.4](03-api-auth-web.md) (E-endpoints), [02 §2.5](02-data-layer.md) |
| live updates | [03 §C](03-api-auth-web.md), [05 §B.7](05-verification.md) |
| attachment download | [03 §E](03-api-auth-web.md), [05 §B.12](05-verification.md) |
| migrations on an empty database and on one imported from a Postgres fixture | [01](01-schema.md), [04 §B](04-data-cutover.md), [05 §B.2–B.3](05-verification.md) |
| no Supabase, Postgres or Render dependency | [05 §B.9](05-verification.md) |

Deploying the image to the server is not part of this plan: the server pulls
signed images itself, and another agent owns that side. The cutover runbook in
[04 §C](04-data-cutover.md) is the operator's checklist for that day.

## The parts

| Part | What it covers | Size |
|---|---|---|
| [01 — Schema](01-schema.md) | Every table, column, constraint, index, trigger and policy, Postgres → SQLite, generated from the live schema; the draft DDL was executed in SQLite (27/30 parsed as generated; the 3 failures and 10 other hand items are resolved at the end) | 30 tables, 458 columns, 149 constraints, 109 indexes |
| [02 — Data layer](02-data-layer.md) | All 73 live functions and 26 triggers: callers, Postgres features, the Python port, size, tests; all 130 `.table(` sites, 37 asyncpg sites, Storage, the work listener; build order | `backend/selko/db/` |
| [03 — API, auth, web](03-api-auth-web.md) | Every supabase-js call in the web app and its replacement endpoint (25 new endpoints), auth (accounts, tokens, cookies), `/live`, attachments, every web file that changes | `backend/selko/api/`, `frontend/src/` |
| [04 — Data and cutover](04-data-cutover.md) | Table-by-table conversion with checksums, the import tool, the minute-by-minute cutover, rollback at each stage, 15+ risks | `selko_import/`, operator runbook |
| [05 — Verification](05-verification.md) | Fate of all 166 test files, 13 new test groups, every lane/hook/workflow/ops operation by phase, every doc that changes, entry and exit criteria per increment | tests, `scripts/`, `.github/`, docs |

## How it is executed (decision)

The parts were researched against the overview's Q1–Q8, in which Q1–Q5 ship
to today's production (Render + Supabase) one by one before the switch. That
path builds several things twice (auth on Postgres in Q5, then on SQLite in
Q6; live updates on `pg_notify` in Q2, then on the bus; a privilege-revoking
migration in Q3 only for the Postgres interim). **The build goes straight to
SQLite instead:**

1. All work happens on one branch, pushed after every step, with the lanes
   green at each push. `main` keeps running today's Postgres code, so
   production stays deployable from `main` for fixes until the switch;
   `main` is merged into the branch whenever it moves.
2. The branch merges once, when the image job in the end-state table passes.
   From that merge, `main` is SQLite-only and can no longer deploy to Render;
   production stays on the last Postgres build until the cutover
   ([04 §C](04-data-cutover.md)). The `deploy-production` operation was
   removed with `ops.yml`; a merge now pushes the images as `:<sha>`, and
   the `release` job signs them and moves `:main`, which the server follows:
   a merge to `main` is a release.
3. Steps that only existed for the Postgres interim are dropped: Q2's dual
   `realtime.send` + `pg_notify`, Q3's revoke migration, Q5's `accounts` on
   Postgres with its mirror trigger. Everything else in the parts applies,
   in this order:

| Step | Work | Gate to finish |
|---|---|---|
| S0 | Foundation: `selko.db` connection (one writer), codec, migration runner, `0001_initial.sql`, event bus, Dockerfile | **done 2026-11-25**: `test_sqlite_foundation.py` (23 tests), image builds and starts under the limits |
| S1 | Fix what the research found broken today (below), each with a regression test | backend lane — **done 2026-11-25** (fixed within S2–S5; OAuth token encryption stays a follow-up) |
| S2 | Data layer: port the 73 functions and 26 triggers in [02 §5](02-data-layer.md)'s order, then the 130 `.table(` and 37 asyncpg sites; delete `services/pg.py`'s pool and listener; startup lease reset | the rewritten integration suite on a temp SQLite file; [05 §B.4–B.6](05-verification.md) — **done 2026-11-25**: no module imports a hosted-database client (`test_no_hosted_database.py`) |
| S3 | Auth: accounts, bcrypt verification of the carried hashes, access JWT + refresh cookie, rate limits ([03 §B](03-api-auth-web.md)) | [05 §B.8](05-verification.md) — **done 2026-11-25** |
| S4 | Client API: 19 data endpoints + attachment download, the ownership matrix test ([03 §A, §E](03-api-auth-web.md)) | [05 §B.1](05-verification.md) passes for every route — **done 2026-11-25** |
| S5 | `/live` on the bus; the web app moves off supabase-js ([03 §C–D](03-api-auth-web.md)) | frontend lane; web screenshots — **done 2026-11-25** (24 captures over SQLite) |
| S6 | Import tool and its round-trip test on a seeded Postgres fixture ([04 §A–B](04-data-cutover.md)) | [05 §B.3](05-verification.md) — **done 2026-11-25** (`selko_import/fixture/`, exit 5 on a refused row) |
| S7 | Image workflow: build, sign with cosign on `main`, the image job under the VM limits ([05 §B.10](05-verification.md)) | the end-state table — **built 2026-11-25**: `image.yml` + `scripts/image-lane.sh` pass locally; the first green run on `main` completes it |
| S8 | Remove Supabase, asyncpg, Render, `supabase/`, staging tooling; lanes, hooks, CI, CLAUDE.md and docs ([05 §C–D](05-verification.md)) | every lane green; no `supabase`/`asyncpg` in source, lockfile or image — **done 2026-11-25** (`asyncpg` remains only as the workspace root's dependency for `selko_import`, never in the image) |

## Decisions recorded here

| # | Decision | Why |
|---|---|---|
| D1 | Straight to SQLite on one branch (above) | builds nothing twice; `main` stays deployable until the switch |
| D2 | Add `bcrypt` as a dependency | GoTrue stores `$2a$10$` hashes and the standard library cannot verify them; without it every user resets their password |
| D3 | Access token in memory, refresh token in an `HttpOnly; Secure; SameSite=Strict; Path=/auth` cookie | an XSS steals at most a 1-hour token; one process serves both web and API, so the cookie is first-party ([03 §B.7](03-api-auth-web.md)) |
| D4 | `/live` is a streaming `fetch` with the normal `Authorization` header | one auth path; no tokens in URLs or logs ([03 §C.2](03-api-auth-web.md)) |
| D5 | SQLite triggers call Python functions registered on the writer connection for timestamps and events | a write from any other connection fails rather than skipping the event bus ([02 §0](02-data-layer.md)) |
| D6 | `estimated_cost_usd` stays REAL under its name (not micro-dollar integers, as 01 first proposed) | report-only; renaming would ripple for no benefit |
| D7 | The importer lives in a sibling package, `selko_import/`, deleted after the cutover | it needs a Postgres driver, which `selko` must not import ([04 §B.1](04-data-cutover.md)) |
| D8 | Attachment files keep their existing `storage_path` layout | the column's checksum stays valid through the import ([04 §B.7](04-data-cutover.md)) |

## What the research found broken today

Each gets a fix with a regression test in S1 (or is ported correctly in S2 and
tested there). None depends on the migration.

| Finding | Evidence | Fix |
|---|---|---|
| "Ignore sender" fails for any sender with a pending change: `ignore_sender_and_reject_pending` calls `reject_event_change_proposal` with 14 arguments (it takes 13), and the web user has no EXECUTE on it | [02 §0](02-data-layer.md); `to_regprocedure`, `has_function_privilege` on the local schema | port with the right call; test through the API route |
| Five test classes in `backend/tests/test_workers.py` are defined twice; only the second copies run, so one calendar-cancel test and one copy of the event-insert guard never execute | [05 §0](05-verification.md), lines 279–860 vs 861– | delete the duplicates; a test forbidding duplicate names in a test module |
| AST/regex guards scan `Path("backend/selko")` relative to the working directory and pass vacuously when run from `backend/` | [05 §0](05-verification.md) | resolve from `__file__`; require a non-empty file set |
| The database never sends `event_approved`, though calendar workers wait for it (they run only on `nudge()` and the safety poll) | [02 §0](02-data-layer.md) | the port publishes it after commit; a test that approval wakes the worker |
| `api/app.py` starts the worker pool (line 130) before releasing stale leases (lines 134–138) | [02 §0](02-data-layer.md) | startup lease reset before any worker starts |
| The rate-limit key decodes the JWT without checking its signature, so a caller picks whose limit to spend | [03 §B.1](03-api-auth-web.md) | key on the verified subject |
| 13 of 31 web service functions have no caller, including the only attachment download: no user can download an attachment today | [03 §A.1](03-api-auth-web.md) | removed; download added with a UI link (E25) |
| `frontend/src/lib/live-updates.js:3` links a spec that does not exist; two spec front-matter test ids do not exist | [05 §0](05-verification.md) | fix the references |
| OAuth tokens are stored in plaintext in `integrations` | [04 §A](04-data-cutover.md) | unchanged by this plan (carried verbatim, files 0600); encryption is a follow-up |

## Owner decisions still open

- ~~**Real-Gmail tests after staging is gone**~~ — removed with staging and the
  dev↔staging token copier; Gmail is mocked in the suite.
- ~~**Google Photos code (parked)**~~ — removed (#425); the importer refuses a
  source that still holds its data (exit 3).
- **Q0 measurements** (production sizes, users, auth settings, plans) are
  needed for the cutover, not for the build ([04 §C.0](04-data-cutover.md));
  the operator runs them read-only in the Supabase SQL editor.
