# Database Schema Reference

This document describes the Supabase database schema for Selko. All tables are in the `public` schema with Row Level Security (RLS) enabled.

## Tables

### `users`

User profiles linked to Supabase Auth.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | References `auth.users` |
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

**RLS Policies:** Users can view their own folders. Direct authenticated updates are
revoked; `set_email_folder_preference(uuid, boolean)` is the only user preference
mutation and can change only inclusion, override, cursor, and timestamp fields on an
owned eligible user folder. The service role manages discovery and cursor writes.

**RLS Policies:**
- Users can view/update/insert own profile
- Auto-created via trigger on `auth.users` insert

### `integrations`

OAuth tokens for external providers.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Integration ID |
| `user_id` | uuid, FK | References `users.id` |
| `provider` | text | `gmail`, `outlook`, `google_photos`, `google_calendar` |
| `status` | text | `active`, `expired`, `revoked`, `error` |
| `access_token` | text | OAuth access token |
| `refresh_token` | text | OAuth refresh token |
| `token_expiry` | timestamptz | Token expiration time |
| `scopes` | text[] | OAuth scopes granted |
| `provider_email` | text | Email associated with integration |
| `sync_cursor` | text | Provider sync cursor (Gmail history ID or Outlook delta link) |
| `last_photo_sync_at` | timestamptz | Last Google Photos sync time |
| `created_at` | timestamptz | Auto-set |
| `updated_at` | timestamptz | Auto-updated |

**RLS Policies:** Users manage own integrations only.

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
| `body_text` | text | Full plain-text body (used for LLM processing) |
| `body_html` | text | Full HTML body (used for linked image extraction) |
| `content_hash` | text | SHA-256 for deduplication |
| `processing_status` | text | `pending`, `processing`, `processed`, `failed`, `skipped` |
| `processing_error` | text | Last processing error message |
| `processing_outcome` | text | `no_event`, `event_matched`, `event_created`, `event_updated`, `event_created_and_updated`, or `event_cancelled` |
| `processing_explanation` | text | Optional explanation already returned by normal processing |
| `processing_result` | jsonb | Structured processing counts for History |
| `provider_folder_ids` | text[] | Current provider folder/label membership |
| `processed_at` | timestamptz | When processing completed |
| `locked_until` | timestamptz | Worker lock expiration |
| `locked_by` | text | Worker ID that claimed this email |
| `attempts` | integer | Number of processing attempts (default: 0) |
| `max_attempts` | integer | Maximum attempts before permanent failure (default: 3) |
| `next_retry_at` | timestamptz, nullable | Exponential backoff: earliest time to retry (60s * 2^attempts, max 1h) |
| `dead_letter_reason` | text, nullable | Reason for permanent failure (set when max_attempts exceeded) |
| `dead_letter_at` | timestamptz, nullable | When the email was moved to dead letter |
| `created_at` | timestamptz | Auto-set |

**RLS Policies:** Users manage own emails only.

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
| `storage_path` | text | Supabase Storage path |
| `content_hash` | text | SHA-256 for deduplication |
| `created_at` | timestamptz | Auto-set |

**RLS Policies:** Users manage own attachments only.

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
| `status` | text | `pending_review`, `pending_change`, `approved`, `syncing`, `synced`, `sync_failed`, `cancelled`, `rejected` |
| `google_calendar_event_id` | text | Google Calendar event ID after sync |
| `synced_at` | timestamptz | When synced to calendar |
| `locked_until` | timestamptz | Worker lock expiration |
| `locked_by` | text | Worker ID that claimed this event |
| `sync_attempts` | integer | Number of sync attempts (default: 0) |
| `max_sync_attempts` | integer | Maximum sync attempts (default: 3) |
| `sync_error` | text | Last sync error message |
| `next_retry_at` | timestamptz, nullable | Exponential backoff: earliest time to retry sync |
| `dead_letter_reason` | text, nullable | Reason for permanent sync failure |
| `dead_letter_at` | timestamptz, nullable | When the event sync was abandoned |
| `created_at` | timestamptz | Auto-set |
| `updated_at` | timestamptz | Auto-updated |

**RLS Policies:** Users manage own events only.

**Indexes:** Partial index on `(status, updated_at) WHERE status = 'approved'` for efficient claiming.

### `scheduled_tasks`

Scheduled/periodic background tasks (currently only `email_fetch`).

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Task ID |
| `user_id` | uuid, FK | References `users.id` |
| `task_type` | text | Currently only `email_fetch` |
| `payload` | jsonb | Task-specific data |
| `status` | text | `pending`, `processing`, `completed`, `failed` |
| `scheduled_at` | timestamptz | When to process task |
| `locked_until` | timestamptz | Worker lock expiration |
| `locked_by` | text | Worker ID that claimed this task |
| `started_at` | timestamptz | When processing started |
| `completed_at` | timestamptz | When processing completed |
| `last_error` | text | Error message if failed |
| `created_at` | timestamptz | Auto-set |

**RLS Policies:**
- Users can view own scheduled tasks
- Service role has full access (for worker processes)

See `docs/job-queue.md` for full status-based worker details.

### `event_sources`

Links events to their origin sources (emails, Google Calendar matches, etc.).

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Event source ID |
| `event_id` | uuid, FK | References `events.id` |
| `email_id` | uuid, FK, nullable | References `emails.id` (required for email sources) |
| `source_origin` | text | `email`, `google_calendar`, or `google_photos` |
| `google_calendar_source_event_id` | text, nullable | Google Calendar event ID (required for calendar sources) |
| `extracted_data` | jsonb | Raw extraction data from source |
| `event_snapshot_before` | jsonb, nullable | Event fields before an update (undo) |
| `change_set` | jsonb, nullable | Structured field diffs for Changes lane / History |
| `created_at` | timestamptz | Auto-set |

**Constraints:**
- `source_origin` must be one of: `email`, `google_calendar`, `google_photos`
- Email sources require `email_id`; calendar sources require `google_calendar_source_event_id`
- Partial unique indexes: `(event_id, email_id)` for email sources, `(event_id, google_calendar_source_event_id)` for calendar sources

**RLS Policies:** Users manage own event sources only (via `events.user_id`).

### `sender_rules`

Per-user rules for handling emails from specific senders or domains.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Rule ID |
| `user_id` | uuid, FK | References `users.id` |
| `sender_email` | text, nullable | Exact sender email to match |
| `sender_domain` | text, nullable | Domain to match (e.g., `example.com`) |
| `action` | text | `ignore` (skip processing) |
| `created_at` | timestamptz | Auto-set |
| `updated_at` | timestamptz | Auto-updated |

**Constraints:** At least one of `sender_email` or `sender_domain` must be set. Unique per `(user_id, sender_email)` and `(user_id, sender_domain)`.

**RLS Policies:** Users manage own sender rules only.

**Triggers:** `sender_rule_before_delete` — when an ignore rule is deleted (un-ignored), a BEFORE DELETE trigger resets matching `skipped` emails from the last 30 days back to `pending` for reprocessing.

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

**RLS Policies:** Service role only (no direct user access).

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

**RLS Policies:** Users manage own action history only.

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

**RLS Policies:**
- Users can view own LLM call history
- Service role has full access (for backend writes)

**Indexes:**
- `(user_id, started_at DESC)` — user usage queries ordered by date
- `(email_id) WHERE email_id IS NOT NULL` — lookup calls for a specific email
- `(operation_type)` — filter by operation type
- `(success) WHERE success = false` — quickly find failed calls

### `photos`

Synced Google Photos with status-based worker claiming for LLM processing.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Photo ID |
| `user_id` | uuid, FK | References `users.id` |
| `google_photo_id` | text | Google Photos media item ID |
| `filename` | text | Original filename |
| `description` | text | Photo description from Google Photos |
| `mime_type` | text | MIME type (image/jpeg, image/png, etc.) |
| `date_taken` | timestamptz | When the photo was taken |
| `width` | integer | Photo width in pixels |
| `height` | integer | Photo height in pixels |
| `location_latitude` | numeric | GPS latitude |
| `location_longitude` | numeric | GPS longitude |
| `location_display_name` | text | Human-readable location name |
| `storage_path` | text | Supabase Storage path |
| `content_hash` | text | SHA-256 for deduplication |
| `processing_status` | text | `pending`, `processing`, `processed`, `failed`, `skipped` |
| `processing_error` | text | Last processing error message |
| `processed_at` | timestamptz | When processing completed |
| `locked_until` | timestamptz | Worker lock expiration |
| `locked_by` | text | Worker ID that claimed this photo |
| `attempts` | integer | Number of processing attempts (default: 0) |
| `max_attempts` | integer | Maximum attempts before permanent failure (default: 3) |
| `next_retry_at` | timestamptz, nullable | Exponential backoff: earliest time to retry (60s * 2^attempts, max 1h) |
| `dead_letter_reason` | text, nullable | Reason for permanent failure (set when max_attempts exceeded) |
| `dead_letter_at` | timestamptz, nullable | When the photo was moved to dead letter |
| `created_at` | timestamptz | Auto-set |

**RLS Policies:** Users manage own photos only. Service role has full access.

**Indexes:**
- `(processing_status, created_at) WHERE processing_status = 'pending'` for efficient claiming
- `(user_id, created_at DESC)` for user photo listing

**Unique Constraint:** `(user_id, google_photo_id)` prevents duplicate photo records.

## RPC Functions

### Claiming Functions

| Function | Description |
|----------|-------------|
| `claim_unprocessed_email(worker_id, lock_duration)` | Atomically claim next pending email |
| `claim_pending_photo(worker_id, lock_duration)` | Atomically claim next pending photo |
| `claim_approved_event(worker_id, lock_duration)` | Atomically claim next approved event |
| `claim_next_scheduled_task(task_types, worker_id, lock_duration)` | Atomically claim next scheduled task |

### Unlock Functions

| Function | Description |
|----------|-------------|
| `unlock_expired_email_locks()` | Reset expired email locks to pending |
| `unlock_expired_photo_locks()` | Reset expired photo locks to pending |
| `unlock_expired_event_locks()` | Reset expired event locks to approved |
| `unlock_expired_scheduled_tasks()` | Reset expired scheduled task locks |

### Usage Summary

| Function | Description |
|----------|-------------|
| `get_llm_usage_summary(p_user_id, p_start_date, p_end_date)` | Returns aggregated LLM usage stats for a user over a date range: total/successful/failed calls, token counts, latency stats, estimated cost, and per-operation breakdowns. Defaults to current day. Granted to `authenticated` role. |

## Supabase Storage

### Bucket: `attachments`

| Setting | Value |
|---------|-------|
| Access | Private (not publicly accessible) |
| Max file size | 50 MB |
| Path format | `{user_id}/{unique_id}_{filename}` (emails) or `{user_id}/photos/{unique_id}_{filename}` (photos) |

**RLS Policies:** Users can only access files in their own folder (`{user_id}/`).

## Migrations

All schema changes are in `supabase/migrations/`. To apply:

```bash
# Local
supabase db reset

# Remote (staging/production)
supabase db push --linked
```
