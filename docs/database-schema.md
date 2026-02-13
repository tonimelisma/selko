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

**RLS Policies:**
- Users can view/update/insert own profile
- Auto-created via trigger on `auth.users` insert

### `integrations`

OAuth tokens for external providers.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Integration ID |
| `user_id` | uuid, FK | References `users.id` |
| `provider` | text | `gmail`, `google_photos`, `google_calendar` |
| `status` | text | `active`, `expired`, `revoked`, `error` |
| `access_token` | text | OAuth access token |
| `refresh_token` | text | OAuth refresh token |
| `token_expiry` | timestamptz | Token expiration time |
| `scopes` | text[] | OAuth scopes granted |
| `provider_email` | text | Email associated with integration |
| `last_history_id` | text | Gmail sync cursor |
| `created_at` | timestamptz | Auto-set |
| `updated_at` | timestamptz | Auto-updated |

**RLS Policies:** Users manage own integrations only.

### `emails`

Synced Gmail messages with status-based worker claiming.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Email ID |
| `user_id` | uuid, FK | References `users.id` |
| `gmail_id` | text | Gmail message ID |
| `thread_id` | text | Gmail thread ID |
| `subject` | text | Email subject |
| `from_email` | text | Sender email |
| `from_name` | text | Sender name |
| `to_emails` | text[] | Recipient emails |
| `date_sent` | timestamptz | When email was sent |
| `gmail_label_ids` | text[] | Raw labels from Gmail API |
| `is_spam` | boolean | Auto-computed from labels |
| `is_trash` | boolean | Auto-computed from labels |
| `is_promotions` | boolean | Auto-computed from labels |
| `content_hash` | text | SHA-256 for deduplication |
| `processing_status` | text | `pending`, `processing`, `processed`, `failed`, `skipped` |
| `processing_error` | text | Last processing error message |
| `processed_at` | timestamptz | When processing completed |
| `locked_until` | timestamptz | Worker lock expiration |
| `locked_by` | text | Worker ID that claimed this email |
| `attempts` | integer | Number of processing attempts (default: 0) |
| `max_attempts` | integer | Maximum attempts before permanent failure (default: 3) |
| `created_at` | timestamptz | Auto-set |

**RLS Policies:** Users manage own emails only.

**Triggers:** Auto-compute `is_spam`, `is_trash`, `is_promotions` from `gmail_label_ids`.

**Indexes:** Partial index on `(processing_status, created_at) WHERE processing_status = 'pending'` for efficient claiming.

### `attachments`

Email attachment metadata.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Attachment ID |
| `email_id` | uuid, FK | References `emails.id` |
| `user_id` | uuid, FK | References `users.id` |
| `gmail_attachment_id` | text | Gmail attachment ID |
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
| `status` | text | `pending_review`, `approved`, `syncing`, `synced`, `sync_failed`, `cancelled`, `rejected` |
| `google_calendar_event_id` | text | Google Calendar event ID after sync |
| `synced_at` | timestamptz | When synced to calendar |
| `locked_until` | timestamptz | Worker lock expiration |
| `locked_by` | text | Worker ID that claimed this event |
| `sync_attempts` | integer | Number of sync attempts (default: 0) |
| `max_sync_attempts` | integer | Maximum sync attempts (default: 3) |
| `sync_error` | text | Last sync error message |
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

## RPC Functions

### Claiming Functions

| Function | Description |
|----------|-------------|
| `claim_unprocessed_email(worker_id, lock_duration)` | Atomically claim next pending email |
| `claim_approved_event(worker_id, lock_duration)` | Atomically claim next approved event |
| `claim_next_scheduled_task(task_types, worker_id, lock_duration)` | Atomically claim next scheduled task |

### Unlock Functions

| Function | Description |
|----------|-------------|
| `unlock_expired_email_locks()` | Reset expired email locks to pending |
| `unlock_expired_event_locks()` | Reset expired event locks to approved |
| `unlock_expired_scheduled_tasks()` | Reset expired scheduled task locks |

## Supabase Storage

### Bucket: `attachments`

| Setting | Value |
|---------|-------|
| Access | Private (not publicly accessible) |
| Max file size | 50 MB |
| Path format | `{user_id}/{unique_id}_{filename}` |

**RLS Policies:** Users can only access files in their own folder (`{user_id}/`).

## Migrations

All schema changes are in `supabase/migrations/`. To apply:

```bash
# Local
supabase db reset

# Remote (staging/production)
supabase db push --linked
```
