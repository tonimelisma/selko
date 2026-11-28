GOVERNS: backend/selko/db/migrations/** backend/tests/schema_domains.py

# Database Schema Reference

This document describes Selko's database: one SQLite file,
`<SELKO_DATA_DIR>/selko.db`. The schema itself is
[`backend/selko/db/migrations/0001_initial.sql`](../../backend/selko/db/migrations/0001_initial.sql)
(plus any later migration in that directory); this page explains what the
tables mean. Design and decisions: [data layer](data-layer.md).

**Conventions.** Tables are `STRICT`. Ids are UUID text. Timestamps are
fixed-width UTC text `YYYY-MM-DDTHH:MM:SS.ffffffZ` (so text order is time
order); the column tables below still say `timestamptz`, `uuid`, `jsonb` and
`boolean`, read as: timestamp text, UUID text, JSON text under
`CHECK (json_valid(...))`, and `INTEGER` 0/1 under `CHECK (x IN (0,1))`.
`selko.db.codec` converts both ways.

**Ownership.** There is no row-level security. Every public `selko.db` function
that touches a user-owned table takes `user_id` and scopes by it
(`backend/tests/db/test_ownership.py` enforces this); worker-wide functions are
allowlisted there by name. Routes answer another user's row with 404.

**Accounts.** `accounts` (email, bcrypt `password_hash`, confirmation and
sign-in times), `auth_sessions` and `auth_refresh_tokens` (only the SHA-256 of
each refresh token; rotation and reuse detection) belong to
`selko.services.accounts`. `users.id` references `accounts.id`; creating an
account creates its `users` row in the same transaction.

## Tables

### `users`

User profiles; one per account.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | References `accounts.id` |
| `email` | text | User email |
| `display_name` | text | Display name |
| `created_at` | timestamptz | Auto-set |
| `updated_at` | timestamptz | Auto-updated via trigger |

### `email_folders`

Discovered Gmail labels and Outlook folders. User-created folders store the shared
marketing-folder recommendation, durable user override, and (for Outlook) their
folder-specific delta cursor. Eligible provider system folders may store worker
state but are never returned by the Settings API; permanent and hidden system trees
are excluded from discovery and scanning.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Folder preference ID |
| `user_id` | uuid, FK | References `users.id` |
| `integration_id` | uuid, FK | References the connected email integration |
| `provider` | text | `gmail` or `outlook` |
| `provider_folder_id` | text | Provider label/folder ID |
| `parent_folder_id` | text | Provider parent ID when available |
| `name` | text | Folder/label name |
| `full_path` | text | Full nesting context used for classification |
| `folder_kind` | text | `label` or `folder` |
| `is_system` | boolean | Provider-managed folder omitted from Settings |
| `is_scannable` | boolean | Whether the worker may issue provider listing/delta/message requests |
| `is_permanently_excluded` | boolean | Provider or hidden system tree that cannot be configured or scanned |
| `classification_decision` | text | `include`, `exclude`, or `uncertain` |
| `classification_reason` | text | Short persisted recommendation reason |
| `user_override` | boolean | Whether the user decision is durable |
| `is_included` | boolean | Effective source-set decision |
| `sync_cursor` | text | Outlook folder-specific Graph delta cursor |



### `integrations`

OAuth tokens for external providers.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Integration ID |
| `user_id` | uuid, FK | References `users.id` |
| `provider` | text | `gmail`, `outlook`, `google_calendar` |
| `status` | text | `active`, `expired`, `revoked`, `error` |
| `access_token` | text | OAuth access token |
| `refresh_token` | text | OAuth refresh token |
| `token_expiry` | timestamptz | Token expiration time |
| `scopes` | text[] | OAuth scopes granted |
| `provider_email` | text | Email associated with integration |
| `sync_cursor` | text | Provider sync cursor (Gmail history ID or Outlook delta link) |
| `created_at` | timestamptz | Auto-set |
| `updated_at` | timestamptz | Auto-updated |


### `emails`

Synced Gmail and Outlook messages with status-based worker claiming.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Email ID |
| `user_id` | uuid, FK | References `users.id` |
| `email_provider` | text | Ingestion provider (`gmail` or `outlook`) |
| `provider_message_id` | text | Opaque provider message ID |
| `thread_id` | text | Provider conversation/thread ID |
| `subject` | text | Email subject |
| `from_email` | text | Sender email |
| `from_name` | text | Sender name |
| `to_emails` | text[] | Recipient emails |
| `date_sent` | timestamptz | When email was sent |
| `provider_labels` | text[] | Raw provider labels or synthesized Outlook tokens |
| `is_spam` | boolean | Auto-computed from labels |
| `is_trash` | boolean | Auto-computed from labels |
| `is_promotions` | boolean | Auto-computed from labels |
| `is_calendar_invite` | boolean | Meeting request/update/RSVP/cancellation (Outlook `eventMessage` or Gmail `.ics` `METHOD`); never surfaced as a Selko suggestion |
| `body_text` | text | Full plain-text body (used for LLM processing) |
| `body_html` | text | Full HTML body (used for linked image extraction) |
| `content_hash` | text | SHA-256 for deduplication |
| `processing_status` | text | `pending`, `processing`, `processed`, `failed`, `skipped` |
| `processing_error` | text | Last processing error message |
| `processing_outcome` | text | `no_event`, `event_matched`, `event_created`, `event_updated`, `event_created_and_updated`, `event_cancelled`, or `calendar_invite` |
| `processing_explanation` | text | Optional explanation already returned by normal processing |
| `processing_result` | jsonb | Structured processing counts for History |
| `provider_folder_ids` | text[] | Current provider folder/label membership |
| `processed_at` | timestamptz | When processing completed |
| `locked_until` | timestamptz | Worker lock expiration |
| `locked_by` | text | Worker ID that claimed this email |
| `lock_generation` | bigint | Monotonic lease generation; extraction commits are rejected when it is stale |
| `attempts` | integer | Number of processing attempts (default: 0) |
| `max_attempts` | integer | Maximum attempts before permanent failure (default: 3) |
| `next_retry_at` | timestamptz, nullable | Exponential backoff: earliest time to retry (60s * 2^attempts, max 1h) |
| `dead_letter_reason` | text, nullable | Reason for permanent failure (set when max_attempts exceeded) |
| `dead_letter_at` | timestamptz, nullable | When the email was moved to dead letter |
| `created_at` | timestamptz | Auto-set |


**Triggers:** Auto-compute the `is_*` flags from `provider_labels`. Outlook uses
Gmail-style `UNREAD`, `IMPORTANT`, and `STARRED` tokens for the shared trigger.

**Indexes:** Partial index on `(processing_status, created_at) WHERE processing_status = 'pending'` for efficient claiming.

### `attachments`

Email attachment metadata.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Attachment ID |
| `email_id` | uuid, FK | References `emails.id` |
| `user_id` | uuid, FK | References `users.id` |
| `provider_attachment_id` | text | Opaque provider attachment ID |
| `filename` | text | Original filename |
| `mime_type` | text | MIME type |
| `size_bytes` | integer | File size |
| `storage_path` | text | Path under `<SELKO_DATA_DIR>/attachments/` |
| `content_hash` | text | SHA-256 for deduplication |
| `created_at` | timestamptz | Auto-set |


### `email_calendar_components`

Provider-neutral, content-free calendar component metadata captured during email
acquisition. The service role is the only writer/reader; raw UIDs and calendar
payloads are never stored here.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Component ID |
| `email_id` / `user_id` | uuid, FK | Owning email and user |
| `component_index` | integer | Stable VEVENT order within the email |
| `method` | text | iCalendar method or normalized provider method |
| `uid_hash` | text, nullable | SHA-256 of normalized iCalendar UID |
| `recurrence_id` / `recurrence_range` | text, nullable | RFC 5545 recurrence identity |
| `sequence` | integer, nullable | Provider revision sequence |
| `dtstamp` | timestamptz, nullable | Provider revision timestamp |
| `component_status` | text, nullable | Structured component status |
| `start_datetime` / `end_datetime` | timestamptz, nullable | Structured component dates |

Components are replaced only when a new non-empty parse is supplied, so
reconciliation cannot erase a prior parse.


### `event_identity_hints`

Content-free hashes used by the deterministic identity ladder. Hints are
written only by the fenced `commit_email_extraction` function in the same
transaction as the event/source mutation.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Hint ID |
| `user_id` / `event_id` | uuid, FK | Owning user and survivor event |
| `source_email_id` | uuid, nullable | Email that supplied the hint |
| `kind` | text | `ical_uid`, `provider_thread`, `join_url`, or `management_url` |
| `value_hash` | text | SHA-256 canonical identity hash; raw values are never stored |
| `recurrence_id` | text | Recurrence identity, empty for non-occurrences |
| `strength` | text | `authoritative` for iCalendar UID, otherwise `supporting` |
| `sequence` / `dtstamp` | integer / timestamptz | Revision ordering for authoritative hints |
| `created_at` | timestamptz | Auto-set |


Lookup is indexed by `(user_id, kind, value_hash, recurrence_id)`; the same
lookup set participates in the commit fingerprint fence.

### `user_calendar_settings`

Per-user calendar defaults and all-day materialization preference.

| Column | Type | Description |
|--------|------|-------------|
| `user_id` | uuid, PK | References `users.id` |
| `target_calendar_id` | text | Provider calendar id (null = primary) |
| `default_invitees` | text | Comma-separated invitee emails |
| `timezone` | text | IANA timezone (default `America/New_York`) |
| `all_day_display_mode` | text | `all_day`, `day_9_to_5`, `morning_8_to_9`, or `custom` |
| `all_day_custom_start` | time | Required when mode is `custom` |
| `all_day_custom_end` | time | Required when mode is `custom`; must be later than start |
| `updated_at` | timestamptz | Auto-updated |

LLM extractions keep `all_day: true` in `event_sources.extracted_data`. The
display mode materializes the `events` row before dedup/persist. It applies to
single-day events only: a span covering several days stays all-day under every
mode, because stretching a per-day window from the first day's start to the last
day's end makes one continuous block (a skating season became an 8:00 Nov 20 →
9:00 Jan 18 event).


### `events`

Calendar events with status-based worker claiming for sync.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Event ID |
| `user_id` | uuid, FK | References `users.id` |
| `title` | text | Event title |
| `start_datetime` | timestamptz | Event start time |
| `end_datetime` | timestamptz | Event end time |
| `all_day` | boolean | Whether all-day event |
| `location` | text | Event location |
| `description` | text | Event description |
| `source_attribution` | text | Natural English attribution |
| `status` | text | `pending_review`, `approved`, `cancel_queued`, `syncing`, `synced`, `sync_failed`, `cancelled`, `rejected` |
| `review_status` | text | Review lane ownership: `pending_review`, `active`, `rejected`, or `cancelled`. Changes are represented by a pending `event_change_proposals` row, never by `status`. |
| `google_calendar_event_id` | text | Google Calendar event ID after sync |
| `synced_at` | timestamptz | When synced to calendar |
| `recovery_id` | uuid, FK nullable | `integration_recoveries.id` of the generation that requeued this event (audit only; progress counting). `ON DELETE SET NULL`. |
| `created_at` | timestamptz | Auto-set |
| `updated_at` | timestamptz | Auto-updated |


**Indexes:** Partial index on `(status, updated_at) WHERE status = 'approved'` for efficient claiming; partial index on `recovery_id WHERE recovery_id IS NOT NULL`.

### `integration_recoveries`

Durable recovery generations created when Google Calendar reauthorization
unblocks OAuth-parked work. Only `google_calendar` produces rows (email resumes
from provider cursors via `integrations_ensure_email_sync_state` with no
recovery record). Never stores credentials.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Recovery generation |
| `integration_id` | uuid, FK | `integrations.id` (`ON DELETE CASCADE`) |
| `user_id` | uuid, FK | `users.id` — ownership |
| `provider` | integration_provider | `google_calendar` in practice |
| `reason` | text | `initial_connection` or `reauthorization` |
| `status` | text | `pending`, `processing`, `waiting`, `completed`, `completed_with_errors`, `failed`, `superseded` |
| `attempts` / `max_attempts` | integer | Bounded recovery retries (default max 5) |
| `next_retry_at` | timestamptz, nullable | Backoff without blocking a worker |
| `locked_by` / `locked_until` | text / timestamptz | Crash-safe worker claim |
| `recovery_since` | timestamptz, nullable | Last successful sync boundary for expired-cursor recovery |
| `checkpoint` | jsonb | Provider continuation state (unused for Calendar) |
| `discovered_count` | integer | Candidate work found |
| `requeued_count` | integer | Events returned to the normal queue |
| `completed_count` | integer | Work that reached its expected terminal state (synced) |
| `remaining_count` | integer | Current backlog for UI progress |
| `error_code` / `error_detail` | text, nullable | Structured terminal recovery failure |
| `requested_at` / `started_at` / `updated_at` / `completed_at` | timestamptz | Lifecycle timestamps |


**Indexes:** partial unique on `(integration_id) WHERE status IN ('pending','processing','waiting')`; claim index on `(requested_at) WHERE status = 'pending'`.

### `event_sources`

Links events to their origin sources (emails, Google Calendar matches, etc.).

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Event source ID |
| `event_id` | uuid, FK | References `events.id` |
| `email_id` | uuid, FK, nullable | References `emails.id` (required for email sources) |
| `source_origin` | text | `email` or `google_calendar` |
| `source_type` | text | What this source contributed: `new_invitation`, `update`, `cancellation`, `reminder`, or `unknown` |
| `google_calendar_source_event_id` | text, nullable | Google Calendar event ID (required for calendar sources) |
| `extracted_data` | jsonb | Raw extraction data from source |
| `created_at` | timestamptz | Auto-set |

**Constraints:**
- `source_origin` must be one of: `email`, `google_calendar`
- `source_type` must be one of: `new_invitation`, `update`, `cancellation`, `reminder`, `unknown`
- Email sources require `email_id`; calendar sources require `google_calendar_source_event_id`
- Partial unique indexes: `(event_id, email_id)` for email sources, `(event_id, google_calendar_source_event_id)` for calendar sources

Only the data layer's commit and proposal functions write provenance rows.
Proposal payloads and undo snapshots live in `event_change_proposals`, not in
provenance rows.


### `event_change_proposals`

Authoritative lifecycle for update and cancellation proposals. A proposal is
selected by its own UUID and never reconstructed by choosing the latest
`event_sources` row.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Proposal ID |
| `event_id` / `user_id` | uuid, FK | Event and owner |
| `source_id` | uuid, unique FK | Provenance source; deletion is restricted |
| `kind` | text | `material_update` or `cancellation` |
| `status` | text | `pending`, `applied`, `rejected`, `superseded`, `closed_legacy` |
| `change_set` | jsonb | Non-empty reversible field-diff envelope |
| `event_snapshot_before` | jsonb | Non-empty reversible Selko snapshot |
| `resolution_reason` | text, nullable | Safe transition/audit reason |
| lifecycle timestamps | timestamptz | Created, resolved, and updated times |

A partial unique index permits at most one pending proposal per event. Apply,
reject, reopen, and repair resolution are atomic `selko.db.proposals`
transitions; a pending proposal requires `events.review_status='active'`
(checked before commit).


### `email_calendar_components`

Opaque, provider-neutral VEVENT correlation data captured during email
acquisition. `uid_hash` is a SHA-256 hash of the trimmed UID; raw calendar
identifiers and component content are not stored.


**Unique Constraint:** `(email_id, component_index)`.

### `event_repair_audit`

Service-only, append-only audit rows for the reviewed duplicate/cancellation
repair tool. It stores UUIDs, action, reason, actor, and content-free
pre-change hashes/counts; it does not store email or event content.


### `sender_rules`

Per-user rules for handling emails from specific senders or domains.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Rule ID |
| `user_id` | uuid, FK | References `users.id` |
| `sender_email` | text, nullable | Exact sender email to match |
| `sender_domain` | text, nullable | Domain to match (e.g., `example.com`) |
| `action` | text | `ignore` (skip processing) or `auto_approve` (auto-approve new events) |
| `created_at` | timestamptz | Auto-set |
| `updated_at` | timestamptz | Auto-updated |

**Constraints:** At least one of `sender_email` or `sender_domain` must be set. Unique per `(user_id, sender_email)` and `(user_id, sender_domain)` (partial unique indexes, since either column may be null).


**Triggers:** `sender_rule_before_delete` — when an ignore rule is deleted, a BEFORE DELETE trigger resets matching `skipped` emails from the last 30 days back to `pending` for reprocessing, **unless another `ignore` rule for the same sender still exists** (e.g. a duplicate-row cleanup) — the sender is still effectively ignored in that case.

### `oauth_states`

Persistent OAuth state tokens for CSRF protection during OAuth flows.

| Column | Type | Description |
|--------|------|-------------|
| `state` | text, PK | Random state token |
| `user_id` | uuid | User initiating the OAuth flow |
| `provider` | text | OAuth provider (`gmail`, `google_calendar`) |
| `redirect_uri` | text | Where to redirect after OAuth |
| `code_verifier` | text, nullable | PKCE code_verifier (required for token exchange) |
| `created_at` | timestamptz | Auto-set |
| `expires_at` | timestamptz | State token expiration (10 minutes) |


### `action_history`

Records user actions for undo/redo support.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Action ID |
| `user_id` | uuid, FK | References `users.id` (CASCADE delete) |
| `action_type` | text | Action performed (e.g., `approve`, `reject`, `edit`) |
| `entity_type` | text | Type of entity acted on (e.g., `event`) |
| `entity_id` | uuid | ID of the entity |
| `previous_state` | jsonb, nullable | Entity state before the action |
| `new_state` | jsonb, nullable | Entity state after the action |
| `external_resource_id` | text, nullable | External resource ID (e.g., Google Calendar event ID) |
| `created_at` | timestamptz | Auto-set |


**Indexes:** `(user_id, created_at DESC)` for recent actions lookup.

### `llm_call_log`

Audit log of all LLM API calls with prompts, responses, token usage, latency, and cost tracking.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Log entry ID |
| `user_id` | uuid, FK | References `users.id` (CASCADE delete) |
| `operation_type` | llm_operation_type | Enum: `extract_events`, `compare_events`, `merge_events` |
| `model` | text | Model name (e.g., `gemini-3-flash-preview`) |
| `provider` | text, nullable | LLM provider (`gemini`, `moonshot`, `zai`, `qwen`, `deepseek`, `minimax`) |
| `email_id` | uuid, FK, nullable | References `emails.id` (SET NULL on delete) |
| `prompt_text` | text | Full prompt sent to the LLM |
| `response_text` | text, nullable | Full response from LLM (null on error) |
| `prompt_tokens` | integer, nullable | Input token count |
| `completion_tokens` | integer, nullable | Output token count |
| `total_tokens` | integer, nullable | Total token count |
| `started_at` | timestamptz | When the LLM call started |
| `completed_at` | timestamptz, nullable | When the LLM call completed (null if in-progress or failed) |
| `latency_ms` | integer, nullable | API call duration in milliseconds |
| `success` | boolean | Whether the call succeeded (default: true) |
| `error_message` | text, nullable | Error details if failed |
| `error_type` | text, nullable | Error classification (`rate_limit`, `api_error`, etc.) |
| `estimated_cost_usd` | numeric(10,6), nullable | Estimated cost based on token pricing |
| `created_at` | timestamptz | Auto-set |


**Indexes:**
- `(user_id, started_at DESC)` — user usage queries ordered by date
- `(email_id) WHERE email_id IS NOT NULL` — lookup calls for a specific email
- `(operation_type)` — filter by operation type
- `(success) WHERE success = false` — quickly find failed calls

## Data-layer functions

Each is a Python function in `backend/selko/db/` (`emails`, `calendar_work`, `events`,
`proposals`, `recovery`, `parked`, `sender_rules`, `health`, …), running in one
`db.write()` transaction under the single writer. Arguments drop the `p_`
prefixes; owner-facing functions take `user_id` explicitly.

### Claiming Functions

| Function | Description |
|----------|-------------|
| `claim_unprocessed_email(worker_id, lock_duration)` | First opportunistically reclaims one expired `processing` lease elsewhere in the table (retries it if attempts remain, otherwise terminates it as `failed`/`lease_expired_at_limit`), then atomically claims next pending email, oldest `date_sent` first (`NULLS LAST`, then `created_at`) — bulk scans ingest newest-first, so claiming oldest-sent-first avoids an older email "updating" an event already created from a newer one. A `pending` row is invariant-guaranteed claimable: `attempts < max_attempts`, no owner, no unexpired lock (`emails_pending_is_claimable_check`) |
| `fail_email_processing(email_id, worker_id, generation, error_code, error_detail, retry_base_seconds, retry_max_seconds)` | Fenced retry-or-terminate transition for a claimed email; a stale `(worker_id, generation)` is a no-op (`fenced: true`) so a replacement worker's claim is never overwritten |
| `claim_calendar_work_item(worker_id, lease_seconds)` | Atomically claim the next calendar work item with an active provider integration and fence its lease |
| `claim_next_scheduled_task(task_types, worker_id, lock_duration)` | Atomically claim next scheduled task |
| `claim_integration_recovery(worker_id, lock_seconds)` | Atomically claim the next `pending` recovery generation, also reclaiming `processing` rows whose lock expired (crashed-worker self-heal) |

### Unlock Functions

### Extraction commit contract

`commit_email_extraction(email_id, worker_id, generation, decisions, terminal)`
runs as one write transaction. It reads the email row, rejects a stale `(locked_by,
lock_generation)` pair without mutation, applies the full decision array in one
transaction, and then clears the lease. Each decision has the pinned minimum
shape:

```json
{
  "action": "create|update|noop",
  "event_id": "uuid|null",
  "fields": {},
  "source": {"email_id": "uuid", "extracted_data": {}}
}
```

The source object may carry the existing source type, snapshot, change set, and
Google Calendar metadata needed by the New and Changes lanes.

Writing decisions also carry `window_start`, `window_end`, and
`expected_fingerprint`. The fingerprint is the MD5 of comma-joined
`id:updated_at` entries sorted by event UUID, with timestamps rendered in UTC
as `YYYY-MM-DDTHH:MM:SS.USZ`. The commit rechecks that exact local-day band under
the same write transaction before mutating anything (the single writer serializes it); a mismatch
returns `conflict: true` and applies nothing.

| Function | Description |
|----------|-------------|
| `unlock_expired_email_locks()` | Startup-only recovery sweep (not a periodic sweeper): resets expired email locks to pending when attempts remain, terminates exhausted ones as `failed`/`lease_expired_at_limit` — CHECK-safe by construction |
| `unlock_expired_event_locks()` | Reset expired event locks to `cancel_queued` for cancellation work or `approved` for upserts |
| `unlock_expired_integration_recoveries()` | Return crashed-worker recovery claims to `pending` |

### Recovery Functions

| Function | Description |
|----------|-------------|
| `complete_integration_reauthorization(...)` | Atomically upserts OAuth credentials and (for `google_calendar`) supersedes any in-flight recovery generation and schedules a new `pending` one. Preserves an existing refresh token when the provider omits a replacement. |
| `requeue_calendar_recovery_batch(recovery_id, worker_id, batch_size, max_batches)` | Tags a claimed recovery's OAuth-blocked `approved` or `cancel_queued` events with `recovery_id` and advances its status. Events resync through the normal worker queue; returns -1 if the claim was lost. |
| `refresh_waiting_calendar_recoveries(batch_size)` | Recomputes progress for `waiting` recoveries and finalizes ones whose tagged upserts or cancellations all reached a terminal state. |

### Worker-owned cancellation

The email pipeline classifies structured `METHOD:CANCEL` messages and strong
unstructured cancellations. A safe match never creates a row: an event with a
provider identity becomes `cancel_queued`/`cancel`, while a local-only event
becomes terminal `cancelled`. Unmatched and ambiguous cancellations are stored
only as email processing outcomes (`cancellation_unmatched` or
`cancellation_ambiguous`). The calendar worker calls the provider delete
operation, then completes the fenced `calendar_work_items` transition to
`cancelled`; retries, OAuth parking, quota deferral, and expired locks remain
item state. Proposal functions do not perform provider I/O.

### Calendar providers (Google and Outlook)

Outlook Calendar is the second write target.
Provider identity is carried by ids: Google ids are bare, Outlook ids are
`outlook:<graph id>` in `user_calendar_settings.target_calendar_id`,
`events.google_calendar_event_id` and `calendar_entries.provider_event_id`.

| Function / column | Description |
|----------|-------------|
| `calendar_work_items.provider` | `google_calendar` or `outlook`, stamped at first claim; NULL until claimed |
| `calendar_provider_of_id(text)` | Provider that owns a stored calendar or event id |
| `outlook_scopes_allow_calendar(text[])` | Whether a stored Microsoft grant includes `Calendars.ReadWrite` |
| `calendar_integration_writable(user, provider)` | Active integration, and for Outlook a calendar grant |
| `calendar_write_provider(user, event)` | Existing event's calendar, else target calendar's provider, else Google if connected, else writable Outlook |
| `claim_calendar_work_item(worker, lease, providers[])` | Claims only writable providers in `providers` (NULL = all) |
| `requeue_calendar_recovery_batch(...)` | Returns OAuth-parked items of the reconnected provider to `pending` and tags them |

`complete_integration_reauthorization` opens a recovery generation for
`google_calendar`, and for `outlook` only when the grant includes calendar.

### Usage Summary

| Function | Description |
|----------|-------------|
| `get_llm_usage_summary(p_user_id, p_start_date, p_end_date)` | Returns aggregated LLM usage stats for a user over a date range: total/successful/failed calls, token counts, latency stats, estimated cost, and per-operation breakdowns. Defaults to current day. |

### Review List

| Function | Description |
|----------|-------------|
| `ignore_sender_and_reject_pending(p_sender_email, p_sender_domain)` | Retroactive, atomic sender ignore: upserts the `ignore` rule, rejects `pending_review` events sourced by that sender, and rejects active proposals whose provenance source is from that sender. Returns `{rejected_new, discarded_changes}`. |

## Attachment files

| Setting | Value |
|---------|-------|
| Location | `<SELKO_DATA_DIR>/attachments/` |
| Path format | `{user_id}/{unique_id}_{filename}` |
| Writes | temp file, fsync, rename, mode 0600; absolute paths, `..` and anything outside the directory are refused |
| Reads | `GET /attachments/{id}/content`, owner only (another user's id answers 404) |

## Durable email polling v2

The v2 migration adds the following service-owned operational boundary:

| Table | Purpose |
|---|---|
| `email_sync_state` | One lease, cursor timing, health timestamps, and bounded failure state per active Gmail/Outlook integration |
| `email_sync_runs` | Append-only normal, initial, reconciliation, and repair run audit |
| `email_ingestion_items` | Idempotent immutable provider identities queued for independent message acquisition |
| `operational_incidents` | Deduplicated safe opened/resolved health notifications |
| `graph_api_failures` | Redacted Microsoft Graph correlation and retry ledger |

`attachments.ingestion_status`, attempts, retry, and lease columns make
attachment storage independent from provider discovery. Existing stored
attachments are marked `stored`; no existing rows are deleted. The safe
`email_sync_health` view exposes only user-scoped health fields and excludes
leases, tokens, raw error detail, and provider cursors.

The coordination functions are `claim_due_email_sync`,
`claim_due_email_reconciliation`, `heartbeat_email_sync`,
`complete_email_sync`, `fail_email_sync`, `upsert_discovered_email_items`,
`claim_email_ingestion_item`, `complete_email_ingestion_item`,
`fail_email_ingestion_item`, `claim_email_attachment`, and
`finish_email_attachment`. All are service-role functions with a fixed search
path and expired-lease recovery during claims.

`email_sync_state.lease_generation` and `email_sync_runs.lease_generation`
generation-fence the whole claim → heartbeat → complete/fail sequence: a claim
first marks any still-`running` run for that integration `abandoned` (a
crashed worker never completed/failed its run), then issues a new generation.
`heartbeat_email_sync`, `complete_email_sync`, and `fail_email_sync` all
require the caller's `(worker_id, generation)` to still match, so a stale
worker's call is a safe no-op rather than corrupting a reassigned lease. A
partial unique index (`email_sync_runs_one_running_per_integration`) makes "at
most one running run per integration" a database invariant, not a convention.

`health_work_state(warning_seconds)` is the single counted health query:
ready/processing/stale-processing email counts (the same predicates as
`claim_unprocessed_email`), stale sync runs,
ingestion/attachment dead-letter and pending counts, due integrations, the
oldest overdue poll for active integrations, and open incidents — plus its own computed `status`
(`ok`/`degraded`). `/health` and `/health/ingestion` both read it; `/health`
no longer hard-codes `ok`.

Two counts describe stuck email work and they mean different things:

| Column | Meaning | Degrades `status`? |
|---|---|---|
| `unclaimable_pending` | `pending` rows with `attempts >= max_attempts` — rows the claim will never take. `emails_pending_is_claimable_check` makes this impossible, so non-zero means that invariant has been violated | **Yes** — actionable |
| `failed_emails` | `processing_status = 'failed'`, the terminal state written by `fail_email_processing` once retries are exhausted | **No** — history |

Merging them into one column meant a single
permanently failed email pinned `status` to `degraded` forever and made
`assert-health.sh` unsatisfiable, because that file requires the count to be
zero. Production carried 27 terminal failures under the old definition and
reported degraded continuously. A gate that cannot succeed is ignored exactly
as reliably as one that cannot fail.

Reconciliation passes a NULL cursor, so `upsert_discovered_email_items` leaves
`integrations.sync_cursor` and per-folder cursors untouched during a
reconciliation pass; only a cursor-bearing discovery page advances them.

`email_sync_state` is provisioned by the `integrations_ensure_email_sync_state`
trigger whenever a Gmail or Outlook integration becomes active, so a newly
connected account is pollable immediately; reconnecting after an expiry also
clears accumulated backoff without disturbing a live lease.
`request_email_sync_now(integration_id)` brings the next poll forward for a
caller-owned integration and is a no-op while a worker holds the lease.

## Migrations

Migrations live in `backend/selko/db/migrations/NNNN_name.sql` and are applied
by `selko.db.migrate` whenever the process opens the database (or by
`python -m selko.admin migrate`): each runs once, recorded with its hash in
`schema_migrations` (an edited, already-applied file is refused), after a
`VACUUM INTO` backup in `<SELKO_DATA_DIR>/backups/`, with foreign keys checked
before commit. Every database test applies them all to a fresh file.

The database the one-time importer made from the earlier hosted database is kept as the
fixture `backend/tests/fixtures/imported_from_postgres.sql`; every migration must still apply
to it (`backend/tests/db/test_imported_fixture.py`).
