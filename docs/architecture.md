# Architecture

Selko reads a user's email (Gmail, Outlook), extracts calendar events with a multimodal LLM, lets
the user review them in a web app, and writes approved events to Google Calendar or Outlook
Calendar. The human stays in the loop: nothing reaches a calendar the user did not approve, except
updates to events Selko already created and senders the user chose to auto-approve. Module detail
lives in [docs/design/](design/); decisions in [docs/adr/](adr/).

```
                 Browser (SvelteKit web app, served by the same process)
                                   │  one origin, Bearer token
                                   ▼
┌──────────────────────────── selko (one process) ────────────────────────────┐
│  FastAPI: /auth/* (own sign-in) · data routes · provider ops · /live (SSE)   │
│  Workers: email ingestion (Gmail, Outlook) · LLM extraction · calendar writes │
│  selko.db: one writer + WAL readers · Bus / WorkSignals (in-process wake-ups) │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │
                     SELKO_DATA_DIR: selko.db + attachments/ (+ backups/)

Outbound: Gmail API · Microsoft Graph · Google Calendar · LLM provider
```

## Components

| Component | Where | Role |
|---|---|---|
| Web app | built SvelteKit files, served by FastAPI (`mount_web_app`) | The only client ([ADR 0005](adr/0005-web-app-is-the-only-client.md)) |
| API | `selko.api` | Sign-in, data, provider operations, `/live` ([client API](design/client-api.md), [auth](design/auth.md)) |
| Ingestion runtime | `selko.workers.ingestion_runtime` | Provider discovery, acquisition, attachments, health floor, calendar mirror ([workers](design/workers.md)) |
| Worker pool | `selko.workers.pool` | LLM extraction, calendar writes, recovery ([event lifecycle](design/event-lifecycle.md)) |
| Data layer | `selko.db` | One writer, WAL readers, migrations, typed errors, Bus/WorkSignals ([data layer](design/data-layer.md)) |
| Operator commands | `selko.admin` | `migrate`, `delete-account`, `seed-demo`; run beside the server |

Selko is a single asyncio process ([ADR 0001](adr/0001-one-process-one-sqlite-file.md)): the web
app, the API and every background task share one event loop and one database file. Blocking SQLite
and CPU work runs in threads (`db.run(...)`), so the loop keeps serving requests. Three workloads
share it: requests (short reads and writes); I/O-bound background work (provider polling and
downloads; leases in the database make each item single-owner); LLM calls (slow, rate-limited by
per-user daily quotas, run in the worker pool, never inline in a request except an explicit
"process this email").

| Layer | Choice | Why |
|---|---|---|
| Web | SvelteKit 2 + DaisyUI | Small, fast, static build served by the API |
| API | FastAPI (Python) | Async-native; the workload is I/O bound; Pydantic validates requests and LLM output |
| Data | SQLite (WAL, STRICT tables) | One file, no server, transactional, enough for this load ([ADR 0004](adr/0004-no-hosted-database.md)) |
| Files | The data directory | Attachments next to the database; one volume to back up ([ADR 0007](adr/0007-attachments-are-files.md)) |
| Auth | Selko's own | No external auth service ([ADR 0006](adr/0006-own-sign-in.md)) |
| Intelligence | One multimodal LLM | OCR, entity extraction, classification and matching in one model ([ADR 0009](adr/0009-llm-centric-extraction-one-model.md)) |
| Delivery | A signed container image | The server pulls and verifies it ([ADR 0014](adr/0014-merge-to-main-releases-a-signed-image.md)) |

## Data

All state is in `SELKO_DATA_DIR` (`/data` in the image): `selko.db`, `attachments/` and `backups/`.
One process owns the directory ([ADR 0002](adr/0002-one-owner-per-data-directory.md)); one writer
connection makes every write ([ADR 0003](adr/0003-one-writer-many-readers.md)). Every fact has one
owner ([ADR 0012](adr/0012-one-state-owner-per-concern.md)); ownership between users is the
`user_id` argument of every data-layer function
([ADR 0016](adr/0016-ownership-by-user-id-in-the-data-layer.md)). Tables:
[database schema](design/database-schema.md).

## Flows

1. **Ingestion.** Each active Gmail or Outlook integration has a leased `email_sync_state`. Gmail
   uses paginated initial scans plus History cursors; Outlook resolves immutable well-known folder
   ids and keeps one delta cursor per included folder; periodic reconciliation backfills. Each
   message is saved atomically with its attachment descriptors and calendar components
   (`save_email_with_attachment_descriptors`); attachments download independently with their own
   retries. Requirements: [ingestion](requirements/ingestion.md).
2. **Extraction.** A committed pending email wakes the worker pool by signal
   ([ADR 0008](adr/0008-work-arrives-by-signal.md)). The LLM (or the `.ics` parser) proposes events;
   identity hints and the resolution ladder match them to existing events; the fenced commit writes
   every decision with an explicit intent
   ([ADR 0010](adr/0010-explicit-extraction-intent-and-declined-terminal.md),
   [ADR 0011](adr/0011-parallel-extraction-fenced-commit.md)). Requirements:
   [extraction](requirements/extraction.md).
3. **Review.** The web app shows New and Changes lanes, updated live over `GET /live`. Accept,
   reject, apply-change and undo are owner-scoped routes. Requirements: [review](requirements/review.md),
   [web](requirements/web.md).
4. **Calendar delivery.** Decisions enqueue `calendar_work_items`; the calendar worker is the only
   provider writer, for Google and Outlook through one code path. A read-only calendar mirror feeds
   identity matching. Requirements: [calendar](requirements/calendar.md).

## Security model

- Data isolation: every user-owned data-layer function scopes by `user_id`; routes answer another
  user's id with 404.
- Sign-in: bcrypt, short-lived access tokens in memory, a rotating HttpOnly refresh cookie.
- OAuth: minimal scopes ([integrations](design/integrations.md)); tokens never leave the API.
- Storage: attachment paths outside the directory are refused; downloads are owner-only.
- The container: non-root user, read-only root filesystem, no capabilities, no new privileges, a
  memory limit, one writable volume.
- Keys are read from Azure Key Vault by the process at startup
  ([ADR 0013](adr/0013-keys-from-key-vault-at-startup.md)). Requirements:
  [privacy](requirements/privacy.md).

## Failure handling

- Leases with generation fences make every claim single-owner; a crashed worker's work is reclaimed
  at the next claim; every lease is released at startup.
- A provider outage trips a per-provider circuit breaker; user-auth failures never trip it and
  instead wait for a reconnect, whose recovery generation requeues the blocked work.
- Health (`/health`, `/health/ingestion`, `/health/egress`) reports counted work state, request
  errors per hour, memory and egress, and every signal can return to green
  ([ADR 0015](adr/0015-health-signals-return-to-green.md)). Requirements:
  [operations](requirements/operations.md).
- When to break the monolith: CPU saturation → a process pool first; write contention (measured
  `DbBusy`, write latency) → batch writes, a database server last; memory → raise the limit before
  splitting.
