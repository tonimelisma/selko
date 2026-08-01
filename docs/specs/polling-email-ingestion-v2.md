# Polling Email Ingestion v2

**Status:** Proposed

## Purpose

Replace Selko's fragile mailbox-wide `scheduled_tasks` fetch loop with a
durable, polling-only reconciliation pipeline. The new design must guarantee
that every eligible message is durably discovered, independently retried, and
eventually processed without allowing one bad message, attachment, expired
lease, API deployment, or transient provider failure to stop later polling.

This is a replacement design, not a patch to the existing task loop. Keep the
working provider adapters and downstream email-to-event processing, but move
poll coordination and ingestion durability onto explicit database state.

The first production acceptance account is the Outlook integration for
`toni@melisma.net`. Do not put that address, provider message IDs, subjects,
senders, bodies, tokens, or other production content in fixtures or logs.

## Production evidence motivating the replacement

The August 1, 2026 production audit found:

- Gmail polling completed approximately every 15 minutes.
- The Outlook integration for `toni@melisma.net` had 289 failed fetch tasks and
  no completed fetch task.
- One Outlook task remained `processing` after its lease expired. Scheduler
  deduplication treated it as active and stopped enqueueing Outlook work.
- Outlook fetches repeatedly failed on unsupported `video/mp4` and Google
  document attachment MIME types because attachment storage was inside the
  folder/cursor transaction.
- Transient Supabase/network errors and Microsoft 401 responses failed entire
  mailbox passes.
- A direct metadata-only comparison found 62 eligible Outlook messages missing
  from Selko, including 42 read messages in Archive.

The implementation must address the structural causes represented by those
facts. A production repair or one-time backfill alone is not sufficient.

## Product contract

### Eligible email guarantee

For every active email integration, Selko guarantees:

> Every message entering an included, scannable provider folder after the
> integration watermark is durably discovered and processed, regardless of
> whether it is read, unread, archived, moved, or relabeled.

Read state is metadata only. It must never determine discovery eligibility.
Archive is included by default.

The existing permanent exclusions remain unchanged unless a separate product
decision changes them:

- Gmail: Spam, Trash, Drafts, Sent, Promotions, Social, and Forums.
- Outlook: Junk, Deleted Items, Drafts, Sent Items, Outbox, hidden search and
  recovery trees, and other existing permanent system exclusions.
- A user-created folder classified or manually set as excluded is outside the
  guarantee until it is included again.

When an excluded user folder is enabled, its first v2 poll performs the normal
bounded initial scan before committing a cursor.

### Polling only

Do not add Gmail Pub/Sub, Microsoft Graph subscriptions, webhooks, or another
event-driven ingestion trigger. The system uses:

- frequent cursor-based polling for low latency;
- overlapping cursorless reconciliation for completeness;
- database leases for safe concurrency and recovery.

### Default timing

- Poll coordinator tick: every 60 seconds.
- Normal integration poll target: every 5 minutes.
- Transient retry: exponential backoff with jitter, starting at 1 minute and
  capped at 30 minutes.
- Daily reconciliation: every included folder, trailing 30 days.
- Weekly reconciliation: every included folder, trailing 90 days.
- Health warning: no successful normal poll for 30 minutes.
- Health critical: no successful normal poll for 60 minutes.

Put timing values in `Config` with environment-variable overrides. Tests must
inject short values; do not sleep for production durations.

## Non-goals

- Do not redesign email-to-event extraction, matching, or approval behavior.
- Do not change folder-classification product policy.
- Do not expose email bodies, provider IDs, or raw operational errors in alerts.
- Do not build a general-purpose workflow engine.
- Do not split Selko into networked microservices.
- Do not delete existing email history during migration.
- Do not make attachment completion a prerequisite for body extraction unless
  the attachment is supported and required for the email's ready state.

## Mandatory production bug closure

The v2 increment is not complete until every observed ingestion failure below
has a regression test, an implemented fix, and production verification:

| Observed failure | Required closure |
|---|---|
| Expired `processing` task permanently suppresses later Outlook polls | Replace timer-task deduplication with claim-time lease recovery. |
| Startup recovery races with workers and misses locks that expire later | Remove startup-only recovery; every claim treats expired work as eligible. |
| Five-minute lease expires during 8–14-minute Outlook runs | Heartbeat owned leases between every provider page/folder and slow operation. |
| Unsupported `video/mp4` or Google-document MIME fails the whole sync | Make attachment handling independent and terminally mark unsupported types. |
| Supabase/network read failures fail entire mailbox passes | Retry bounded safe operations and preserve page/cursor durability. |
| Microsoft 401 leaves integration/task state inconsistent | Validate MSAL output, retry one refresh, then atomically expire and alert. |
| Outlook cursor state exists but `last_sync_at` is not meaningful | Update success timestamps from completed durable runs for both providers. |
| No runtime notification occurs while an integration is stale | Persist deduplicated incidents and send opened/resolved notifications. |
| Read archived mail is missing | Treat read state as metadata and reconcile every included folder. |
| Repeated folder replay performs large duplicate work | Advance cursors after durable identity discovery; acquire messages independently. |

Do not defer these items as follow-up polish. They are acceptance blockers for
cutting over from the old poller.

## Current code to retain

Retain and adapt these working boundaries:

- `backend/selko/services/gmail.py`
  - credential loading;
  - label discovery;
  - paginated Gmail History;
  - paginated bounded message listing;
  - metadata and full-message fetching.
- `backend/selko/services/outlook.py`
  - token acquisition;
  - immutable message IDs;
  - well-known-folder resolution;
  - folder discovery and normalization;
  - paginated per-folder delta requests;
  - full-message and attachment fetching.
- `backend/selko/services/email_folders.py`
  - durable folder identity;
  - permanent exclusions;
  - inclusion and user overrides.
- `backend/selko/services/emails.py`
  - email parsing/upsert helpers;
  - the unique identity `(user_id, email_provider, provider_message_id)`;
  - downstream processing claim/retry behavior.
- `backend/selko/workers/email_process.py` and the existing event pipeline.

Do not retain the old `email_fetch` orchestration as a parallel fallback after
cutover. Two independent pollers would make ownership and health ambiguous.

## Target runtime topology

Use the existing repository and Python package in two Render processes:

```text
selko-app-production
  uvicorn / FastAPI only

selko-worker-production
  poll coordinator
  provider discovery workers
  message acquisition workers
  attachment workers
  existing email/event workers
  health evaluator and notification dispatcher
```

This remains an async monolith at the code level. The worker process must use
the same `Config`, service-role Supabase client, provider services, and logging
configuration as the API. It must not expose an HTTP API other than an optional
minimal Render health port if Render requires one.

Add:

- `backend/selko/worker_app.py` with an async `main()` and graceful shutdown.
- A package script or documented command such as
  `uv run python -m selko.worker_app`.
- A worker service definition in the repository's Render configuration or a
  documented dashboard creation step if the service cannot be declared in code.

The API's FastAPI lifespan must no longer start APScheduler or `WorkerPool` in
production after cutover. During migration, guard old and new paths with an
explicit environment flag; never let both claim the same integration.

## Database design

Create one migration under `supabase/migrations/`. Use the next available UTC
timestamp prefix at implementation time. Update `docs/database-schema.md` after
the implementation ships.

### 1. `email_sync_state`

One row per Gmail or Outlook integration.

```sql
CREATE TABLE public.email_sync_state (
    integration_id uuid PRIMARY KEY
        REFERENCES public.integrations(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    provider text NOT NULL CHECK (provider IN ('gmail', 'outlook')),
    initial_watermark_at timestamptz NOT NULL,
    next_poll_at timestamptz NOT NULL DEFAULT now(),
    lease_owner text,
    lease_expires_at timestamptz,
    last_started_at timestamptz,
    last_discovery_at timestamptz,
    last_success_at timestamptz,
    last_reconciled_at timestamptz,
    consecutive_failures integer NOT NULL DEFAULT 0,
    last_error_code text,
    last_error_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
```

Requirements:

- Unique ownership comes from the primary key; do not create one timer task per
  interval.
- `initial_watermark_at` is the oldest date Selko promises to cover for this
  integration. For migrated integrations, set it to the earliest existing
  eligible email date, capped by the original 14-day initial-sync policy.
- RLS allows users to read a safe view of their health state but not mutate it.
- Token, cursor, lease owner, and raw failure detail remain service-only.

### 2. `email_sync_runs`

Append-only operational audit for each normal or reconciliation run.

```sql
CREATE TABLE public.email_sync_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_id uuid NOT NULL
        REFERENCES public.integrations(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    provider text NOT NULL CHECK (provider IN ('gmail', 'outlook')),
    run_kind text NOT NULL
        CHECK (run_kind IN ('initial', 'incremental', 'daily_reconcile',
                            'weekly_reconcile', 'manual_repair')),
    status text NOT NULL
        CHECK (status IN ('running', 'completed', 'failed', 'abandoned')),
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    folders_attempted integer NOT NULL DEFAULT 0,
    folders_completed integer NOT NULL DEFAULT 0,
    provider_ids_seen integer NOT NULL DEFAULT 0,
    ingestion_items_inserted integer NOT NULL DEFAULT 0,
    ingestion_items_existing integer NOT NULL DEFAULT 0,
    error_code text,
    error_detail text
);
```

`error_detail` is service-only and sanitized. Never store tokens, bodies,
subjects, sender addresses, provider response HTML, or entire exception dumps.

### 3. `email_ingestion_items`

The durable boundary between provider discovery and local acquisition.

```sql
CREATE TABLE public.email_ingestion_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_id uuid NOT NULL
        REFERENCES public.integrations(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    provider text NOT NULL CHECK (provider IN ('gmail', 'outlook')),
    provider_message_id text NOT NULL,
    provider_folder_ids text[] NOT NULL DEFAULT '{}',
    change_kind text NOT NULL DEFAULT 'upsert'
        CHECK (change_kind IN ('upsert', 'membership_change', 'removed')),
    first_discovered_at timestamptz NOT NULL DEFAULT now(),
    last_discovered_at timestamptz NOT NULL DEFAULT now(),
    acquisition_status text NOT NULL DEFAULT 'pending'
        CHECK (acquisition_status IN
               ('pending', 'processing', 'completed', 'retry', 'dead_letter',
                'removed')),
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 8,
    next_retry_at timestamptz,
    lease_owner text,
    lease_expires_at timestamptz,
    last_error_code text,
    last_error_at timestamptz,
    email_id uuid REFERENCES public.emails(id) ON DELETE SET NULL,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (integration_id, provider_message_id)
);
```

Rediscovery must update `last_discovered_at`, union folder membership, and
revive a retryable item without resetting completed work. A completed item is
not reacquired solely because reconciliation sees it again.

### 4. Attachment state

Extend the existing `attachments` table instead of creating another binary
metadata table:

```text
ingestion_status: pending | processing | stored | unsupported | retry | dead_letter
attempts
max_attempts
next_retry_at
locked_by
locked_until
ingestion_error_code
```

Ensure a unique constraint exists on `(email_id, provider_attachment_id)`.
If existing rows make that impossible, deduplicate them in the migration before
adding the constraint.

### 5. `operational_incidents`

Persist alert state so repeated health checks do not repeatedly notify Toni.

```sql
CREATE TABLE public.operational_incidents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_key text NOT NULL UNIQUE,
    integration_id uuid REFERENCES public.integrations(id) ON DELETE CASCADE,
    user_id uuid REFERENCES public.users(id) ON DELETE CASCADE,
    incident_type text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('warning', 'critical')),
    status text NOT NULL CHECK (status IN ('open', 'resolved')),
    safe_summary text NOT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    opened_notification_sent_at timestamptz,
    resolved_notification_sent_at timestamptz
);
```

Only the service role may read or mutate this table initially. Do not add a UI
in this increment.

### 6. `graph_api_failures`

Implement the runtime ledger specified in
`docs/microsoft-graph-failure-ledger.md`. All Outlook and future OneDrive Graph
requests must flow through a shared `backend/selko/services/msgraph.py` helper
that records structured, redacted failures before applying retry/resync policy.

The shared helper must preserve:

- HTTP status and Graph error code;
- `request-id`, `client-request-id`, and `Retry-After` when present;
- safe operation and URL template;
- failure ownership classification;
- the sync run ID and attempt.

It must never persist delta/next-link URLs because they contain opaque state
tokens. Store only normalized endpoint templates.

## Required database functions

Implement coordination as `SECURITY DEFINER` database functions with fixed
`search_path`, explicit grants, and tests.

### `claim_due_email_sync(p_worker_id, p_lease_seconds)`

In one transaction:

1. Select an active Gmail/Outlook integration whose `next_poll_at <= now()`.
2. Treat a missing or expired lease as claimable.
3. Use `FOR UPDATE SKIP LOCKED`.
4. Set `lease_owner`, `lease_expires_at`, and `last_started_at`.
5. Create and return an `email_sync_runs` row of the appropriate kind.

Order by `next_poll_at`, then `last_success_at NULLS FIRST`, so a failing account
cannot permanently starve another account.

### `heartbeat_email_sync(...)`

Extend the lease only when both integration ID and lease owner match. Call it:

- between provider pages;
- between Outlook folders;
- before and after a large database upsert.

If heartbeat ownership is lost, stop the run without committing a new cursor.

### `complete_email_sync(...)`

Atomically:

- verify lease ownership;
- mark the run complete;
- clear the lease;
- set `last_discovery_at` and `last_success_at`;
- reset `consecutive_failures` and error state;
- set `next_poll_at` to the next normal interval.

### `fail_email_sync(...)`

Atomically:

- mark the run failed;
- clear the lease;
- increment `consecutive_failures`;
- store a bounded stable error code;
- calculate `next_poll_at` using capped exponential backoff and jitter.

Authentication errors additionally mark the integration `expired`. A transient
provider or Supabase failure must not do so.

### `upsert_discovered_email_items(...)`

Accept a bounded JSON array or typed arrays for one provider page. In one
transaction:

- insert new immutable message identities;
- merge folder membership for existing identities;
- update the sync-run counters;
- persist the new provider cursor only after all identities for that cursor
  boundary are durable.

Do not send an entire large mailbox in one RPC. Commit one provider page at a
time, while retaining the previous externally committed cursor until all pages
for the run are complete. Store an in-progress page cursor on the run if needed,
but do not expose it as the recovery cursor.

### Acquisition and attachment claim functions

Provide atomic `FOR UPDATE SKIP LOCKED` claim functions that:

- automatically reclaim expired leases;
- increment attempts on claim;
- respect `next_retry_at`;
- never claim completed, removed, unsupported, or dead-lettered rows.

Unlike the current design, no startup-only unlock function is required.

## Provider discovery algorithms

### Gmail incremental poll

Use the integration's durable `sync_cursor`:

1. Load credentials and confirm the integration is active.
2. Refresh label discovery and inclusion policy.
3. Call paginated Gmail History from the committed cursor.
4. Collect message IDs from additions, deletions, and label changes.
5. Fetch metadata only to determine permanent/user exclusion.
6. Upsert every eligible ID into `email_ingestion_items`.
7. Record membership changes or removal for already-known messages.
8. Heartbeat between pages.
9. Commit the new History cursor only after every History page and every
   discovered identity is durable.

Do not fetch full bodies or attachments in this loop.

If Gmail reports an expired History cursor:

1. Capture the replacement mailbox History ID before reconciliation.
2. Run the trailing 30-day Gmail search using current exclusions.
3. Drain all pages and upsert identities.
4. Commit the captured replacement cursor only after the search succeeds.

This preserves the race protection already implemented in
`_process_gmail_reliable` while moving acquisition out of the cursor boundary.

### Outlook incremental poll

1. Acquire a Microsoft token.
2. Resolve permanent well-known folder IDs.
3. Refresh folder discovery and inclusion policy.
4. Iterate every included, scannable folder independently.
5. Call Graph delta with `Prefer: IdType="ImmutableId"`.
6. Drain all pages.
7. Upsert each changed immutable ID and folder membership into the ingestion
   ledger.
8. Apply removed membership without treating a folder move as Trash.
9. Commit that folder's new delta cursor only after its discovered identities
   are durable.
10. Heartbeat between pages and folders.

A failure in one folder must be recorded, but it must not roll back already
completed folder cursor commits. The integration run is successful only when
all included folders succeed; a partial run retries failed folders next time.

If a folder returns 404 after discovery, remove its configuration as the current
code does. If its delta cursor requires resync, run that folder's bounded 30-day
listing without clearing other folder cursors.

Microsoft-specific requirements from official Graph documentation:

- Follow returned `@odata.nextLink` and `@odata.deltaLink` URLs verbatim; do not
  reconstruct them or append the initial query parameters again.
- Continue through empty pages when a next link exists.
- Treat delta tokens as opaque and potentially expiring.
- Handle HTTP 410/`syncStateNotFound` with the documented fresh enumeration
  path, recording the reset in the Graph failure ledger.
- Send `Prefer: IdType="ImmutableId"` on every request returning Outlook item
  IDs. IDs are case-sensitive.
- Generate `client-request-id` and request its return for support correlation.
- On 429, honor `Retry-After`; use exponential backoff only when it is absent.

See `docs/microsoft-graph-failure-ledger.md` for researched sources and known
production signatures.

### Reconciliation poll

Reconciliation deliberately ignores the delta cursor but never replaces it:

1. List immutable IDs received inside the configured lookback for every
   included folder.
2. Upsert them into `email_ingestion_items`.
3. Count provider IDs, newly inserted IDs, and existing IDs.
4. Complete only after every page is drained.

The same identity may appear in multiple Gmail labels or Outlook folders. Count
unique `(integration_id, provider_message_id)` values for coverage reporting.

Daily and weekly reconciliations use the same function with different lookback
windows and `run_kind` values. Tests must prove that repeated reconciliation is
idempotent.

## Message acquisition algorithm

The acquisition worker claims one `email_ingestion_items` row at a time:

1. Fetch the provider's full message by immutable ID.
2. If the provider returns 404, mark the item `removed`; do not retry forever.
3. Parse it with the existing Gmail or Outlook parser.
4. Upsert `emails` using the existing provider identity constraint.
5. Preserve/union current folder membership.
6. Enumerate attachment descriptors and upsert attachment rows as `pending`.
7. Link `email_id` and mark acquisition `completed`.
8. Leave the existing email trigger/worker to process the email when its body is
   ready under the attachment-readiness rules below.

Classify failures into stable codes, for example:

- `provider_auth_expired`
- `provider_rate_limited`
- `provider_transient`
- `provider_message_missing`
- `database_transient`
- `parse_invalid`
- `unknown`

Store a short sanitized detail separately, capped in length. Use retry headers
for provider rate limits. Dead-letter deterministic parse failures only after
the configured maximum attempts.

## Attachment algorithm and readiness

Attachment workers claim one attachment at a time.

1. Inspect provider metadata before downloading when possible.
2. If the MIME type or attachment kind is unsupported, mark `unsupported` and
   do not fail the email.
3. Download and store supported attachments idempotently.
4. Retry transient provider/storage errors independently.
5. Dead-letter deterministic failures after the attempt cap.

An email becomes eligible for LLM processing when:

- its body acquisition is complete; and
- every supported, LLM-relevant attachment is `stored`, `unsupported`, or
  `dead_letter`.

Unsupported attachments must be represented in structured processing metadata
so the system can explain internally that only the body and supported files were
analyzed. Do not show raw storage errors to the user.

Calendar invitation handling and sender-ignore behavior remain downstream and
unchanged.

## Worker loops and shutdown

Implement independent async loops with bounded concurrency:

- one sync coordinator loop;
- configurable provider-discovery concurrency, default 2;
- configurable message-acquisition concurrency, default 4;
- configurable attachment concurrency, default 4;
- the existing LLM/event work concurrency.

Reuse long-lived Supabase/httpx/provider clients where safe. Do not create a new
Supabase client every idle polling iteration; the current worker comments
document the production memory leak this caused.

On SIGTERM/SIGINT:

1. Stop claiming new work.
2. Cancel or finish work within Render's shutdown window.
3. Do not mark unfinished work complete.
4. Allow leases to expire and be reclaimed by the next process.

All network calls require explicit connect/read/overall timeouts. Provider page
loops must have a maximum run duration and continue to heartbeat while owned.

## Circuit breakers

Do not use one process-global provider circuit breaker as the authoritative
state. Persist failures per integration.

A local circuit breaker may reduce pressure during a provider-wide outage, but:

- it must not prevent lease recovery;
- it must not hide the integration's next retry time;
- one user's auth failure must not suppress other users;
- reconciliation must resume automatically after recovery.

## Health evaluation and notifications

Add `backend/selko/services/email_sync_health.py` and run it every five minutes.

Open or refresh a deduplicated incident when:

- an active integration has no `last_success_at` after its initial grace period;
- `last_success_at` is older than 30 minutes (warning) or 60 minutes (critical);
- a lease is expired beyond two coordinator ticks;
- three consecutive sync runs fail;
- an integration becomes `expired`;
- an acquisition item or supported attachment reaches dead letter;
- reconciliation inserts one or more previously missing message IDs.

Resolve the incident after the integration completes a normal poll and any
associated discrepancy returns to zero.

Add a small notification interface:

```python
class OperationalNotifier(Protocol):
    async def send_incident_opened(self, incident: SafeIncident) -> None: ...
    async def send_incident_resolved(self, incident: SafeIncident) -> None: ...
```

Implement one transactional-email provider selected during implementation.
Configuration must include sender and recipient addresses. Default the
production recipient to an explicit environment variable; do not hard-code
`toni@melisma.net` in application code.

The email contains only:

- environment;
- provider and safe account label;
- incident type and severity;
- first/last successful timestamps;
- safe remediation such as reconnecting OAuth.

It must not contain message subjects, senders, bodies, provider IDs, tokens, or
raw exception pages. Notification delivery failure remains retryable and must
not block ingestion.

## Logging and metrics

Use structured log fields for:

- integration ID;
- provider;
- run ID and kind;
- folder row ID, not display name when avoidable;
- stable error code;
- counters and durations.

Never log access/refresh tokens, provider authorization headers, email bodies,
subjects, sender addresses, attachment content, or raw provider payloads.

Required run metrics:

- poll delay from `next_poll_at`;
- discovery duration;
- provider pages and unique IDs seen;
- new versus existing ingestion items;
- acquisition queue age;
- attachment queue age;
- reconciliation discrepancy;
- consecutive failure count.

## Migration and cutover

### Phase 1: Schema and dormant code

1. Add tables, columns, indexes, RLS, and database functions.
2. Add database and backend unit tests.
3. Add the new worker behind `ENABLE_EMAIL_INGESTION_V2=false`.
4. Leave the existing production path active.

### Phase 2: Backfill durable state

Write an idempotent migration or service command that:

1. Creates `email_sync_state` for every active Gmail/Outlook integration.
2. Creates completed ingestion items for existing email rows.
3. Links those items to their `emails.id`.
4. Preserves integration and folder cursors.
5. Creates pending attachment state only for attachments not already stored.
6. Does not requeue already processed email rows.

Print counts only. Do not print email content or provider message IDs.

### Phase 3: Staging shadow comparison

Do not run two writers. In shadow mode, v2 may list and compare IDs but must not
commit cursors or enqueue acquisition work.

For Gmail and Outlook staging accounts:

- compare eligible provider IDs with existing emails;
- exercise Archive and read-message cases;
- inject an unsupported attachment fixture;
- terminate the worker mid-run and verify lease recovery;
- confirm reconciliation is idempotent.

### Phase 4: Production cutover

Production deployment requires explicit user approval under repository policy.

1. Deploy schema and dormant worker code.
2. Backfill v2 state.
3. Provision `selko-worker-production` with v2 enabled.
4. Disable old API background processing before enabling v2 writes.
5. Confirm only one ingestion owner is active.
6. Run a normal poll and manual 30-day reconciliation.
7. Observe health for at least two normal poll intervals.

### Phase 5: Toni repair and acceptance

For `toni@melisma.net`, using identifiers resolved at runtime:

1. Verify OAuth token acquisition or require reconnect if expired.
2. Reconcile every included Outlook folder for 30 days.
3. Confirm Inbox and Archive read messages are included.
4. Confirm the known production discrepancy falls to zero.
5. Confirm new messages appear within the polling SLO.
6. Confirm unsupported attachment types do not fail the folder run.
7. Trigger a safe synthetic failure and confirm one opened notification and one
   resolved notification are delivered.

Do not delete old scheduled-task history until acceptance is complete. After
acceptance, remove old `email_fetch` scheduling code and later clean historical
rows with a separate retention migration.

### Rollback

Rollback must not require dropping v2 tables or losing discovered identities.

1. Disable v2 claims.
2. Stop the dedicated worker.
3. Diagnose before re-enabling the old poller; do not run both writers.
4. Preserve v2 state for forward recovery.

If provider cursors advanced under v2, the old poller may resume only after
verifying it reads the same committed cursors and identity constraints.

## Implementation sequence

Each numbered step should be a reviewable commit or a clearly separated commit
group. A junior developer should complete and validate one step before starting
the next.

1. Add schema tables, indexes, RLS, and safe read views.
2. Add database claim/heartbeat/complete/fail functions and SQL tests.
3. Add sync-state and sync-run Python services.
4. Add ingestion-item claim/retry services.
5. Refactor Gmail discovery to emit durable identities only.
6. Refactor Outlook discovery to emit durable identities per folder.
7. Add message-acquisition workers using existing parsers/upserts.
8. Add independent attachment state and workers.
9. Gate existing email processing on acquisition readiness.
10. Add daily/weekly reconciliation modes.
11. Add the dedicated worker entry point and shutdown behavior.
12. Add health evaluation, incidents, and notifier interface.
13. Add shared Graph transport, runtime failure ledger, and known-failure tests.
14. Add the selected transactional-email implementation.
15. Add idempotent backfill and shadow-comparison commands.
16. Update reference docs, `CLAUDE.md`, environment templates, and Render setup.
17. Run staging cutover and failure drills.
18. Request production deployment approval.
19. Cut over production and complete Toni acceptance.
20. Remove the old poller in a follow-up once production acceptance is stable.

## Test plan

Every production bug fix requires regression coverage. Use anonymized synthetic
identities and content.

### Database tests

- Two workers cannot claim the same integration.
- An expired integration lease is claimable without a startup cleanup call.
- A live lease is not claimable.
- Heartbeat requires matching ownership.
- Completion/failure requires matching ownership.
- Backoff increases and remains capped.
- Ingestion-item upsert is idempotent.
- Folder memberships are unioned deterministically.
- Completed ingestion items are not reset by reconciliation.
- Expired acquisition/attachment leases are reclaimable.
- Users cannot mutate operational state or read service-only error details.

### Gmail tests

- Initial bounded listing drains every page.
- Incremental History drains every page.
- Read and archived messages are discovered.
- Excluded label metadata prevents acquisition.
- Provider IDs are durable before cursor commit.
- Database failure before identity commit leaves the old cursor.
- Failure after identity commit but before acquisition does not lose the ID.
- Expired-cursor recovery closes the existing race.
- Reconciliation overlap creates no duplicates.
- Label changes update membership without duplicate extraction.

### Outlook tests

- Every included folder is polled independently.
- Archive and read messages are discovered.
- Immutable IDs survive Inbox-to-Archive moves.
- Folder delta pagination is complete.
- One folder failure does not roll back completed folder cursors.
- A failed folder is retried on the next poll.
- Cursor expiry resyncs only that folder.
- Folder deletion removes configuration safely.
- Hidden/permanent/user-excluded folders are never requested.
- Reconciliation overlap creates no duplicates.

### Acquisition tests

- A discovered ID survives process termination before body acquisition.
- Repeated acquisition upserts one email.
- Provider 404 becomes terminal `removed`.
- 429 honors bounded retry timing.
- Transient provider/database failures retry.
- Deterministic parse failure eventually dead-letters.
- One poison message does not stop later messages.

### Attachment tests

- Unsupported `video/mp4` becomes `unsupported` without failing email or sync.
- Unsupported Google document MIME becomes `unsupported`.
- Supported files store idempotently.
- One attachment failure does not block other messages.
- Retry and dead-letter transitions are bounded.
- Email readiness treats terminal unsupported/dead-letter states correctly.

### Runtime tests

- API startup does not start ingestion workers under v2.
- Worker shutdown stops claims and leaves recoverable leases.
- Worker restart reclaims expired work.
- A long provider run heartbeats and is not double-claimed.
- Supabase 520-style transient responses do not expire OAuth.
- One integration's auth failure does not block another integration.

### Health and notification tests

- Stale success timestamps open one deduplicated incident.
- Repeated evaluation updates rather than duplicates it.
- Recovery resolves the incident and sends one recovery notification.
- Notification failure retries without blocking ingestion.
- Alert payloads contain no sensitive message or token fields.

### Graph transport and ledger tests

- Every request sends and captures a `client-request-id` safely.
- 429 honors `Retry-After` and does not expire OAuth.
- 429 without `Retry-After` uses capped exponential backoff.
- 410 records a cursor-reset occurrence without persisting the Location token.
- `syncStateNotFound` triggers only the affected collection's resync.
- Empty delta pages with a next link continue paging.
- Next/delta links are followed verbatim.
- Immutable-ID preference is present on every Outlook item-ID request.
- MSAL output without a valid `access_token` issues no Graph request.
- Transport termination is retryable and leaves the committed cursor intact.
- Storage HTTP 415 is classified as downstream rather than Graph failure.
- Ledger rows never contain tokens, email metadata, item IDs, or raw HTML.

## Required local validation

This implementation will touch backend code and Supabase migrations. Before
merge, run:

```bash
uv run pytest backend/tests/ -m "not integration"
```

Also apply migrations to local Supabase and verify a clean schema diff according
to `docs/testing-guide.md`. Add focused integration tests against mocked Gmail
and Graph pagination; do not depend on production accounts for the unit-test
gate.

No frontend, iOS, Android, or screenshot validation is required unless those
platforms are changed to display synchronization health.

## Documentation updates when shipped

- Update `docs/job-queue.md` to describe v2 coordination and remove old
  `scheduled_tasks` email-fetch claims.
- Update `docs/database-schema.md` with all new tables and fields.
- Update `docs/api-workflow.md` with the separate worker process.
- Update provider ingestion reference docs.
- Update `docs/microsoft-graph-failure-ledger.md` with any newly observed
  signatures and close implemented entries.
- Update `.env.example` with v2 timing, enablement, and notification variables.
- Update `CLAUDE.md` architecture principles and reference index.
- Mark this spec **Implemented** only after production acceptance and old-poller
  removal.

## Definition of done

- Polling is owned by the dedicated worker, not FastAPI lifespan.
- No timer-row deduplication can permanently suppress an integration.
- Expired leases are reclaimed during ordinary claims.
- Provider cursors advance after durable identity discovery, not attachment or
  LLM completion.
- Message and attachment retries are independent.
- Read and archived eligible messages are covered.
- Daily and weekly reconciliation are idempotent and measured.
- Runtime incidents produce deduplicated opened and resolved notifications.
- Production has exactly one ingestion owner.
- The `toni@melisma.net` reconciliation discrepancy is zero.
- New eligible mail meets the polling SLO for at least two observed intervals.
- Existing email history and downstream event behavior remain intact.
