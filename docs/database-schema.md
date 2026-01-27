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

Synced Gmail messages.

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
| `created_at` | timestamptz | Auto-set |

**RLS Policies:** Users manage own emails only.

**Triggers:** Auto-compute `is_spam`, `is_trash`, `is_promotions` from `gmail_label_ids`.

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

### `jobs`

Background job queue.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid, PK | Job ID |
| `user_id` | uuid, FK | References `users.id` |
| `job_type` | text | `email_fetch`, `email_process`, `calendar_sync` |
| `status` | text | `pending` → `processing` → `completed`/`failed`/`dead` |
| `payload` | jsonb | Job-specific data |
| `priority` | integer | Higher = more urgent |
| `attempts` | integer | Retry count |
| `locked_until` | timestamptz | Lock expiration |
| `locked_by` | text | Worker ID |
| `created_at` | timestamptz | Auto-set |
| `updated_at` | timestamptz | Auto-updated |

See `docs/job-queue.md` for full job queue details.

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
