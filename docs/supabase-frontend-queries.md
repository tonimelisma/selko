# Supabase Frontend Query Patterns

**This is the canonical reference for all frontend data access.**

All frontends (Web/JS, Android/Kotlin, iOS/Swift) **MUST** use these patterns when accessing data. There is no alternative API for data queries.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SELKO DATA ACCESS ARCHITECTURE                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ┌──────────────────────────────────────────────────────────────┐  │
│   │   ALL DATA QUERIES → Supabase Direct (this document)         │  │
│   │   - List/view emails, events, integrations, attachments      │  │
│   │   - Update event status (approve, reject)                    │  │
│   │   - Download attachments from storage                        │  │
│   │   - Read user settings                                       │  │
│   │                                                              │  │
│   │   RLS (Row Level Security) handles authorization             │  │
│   └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│   ┌──────────────────────────────────────────────────────────────┐  │
│   │   SERVER-SIDE ONLY → Python API (9 endpoints)                │  │
│   │   - OAuth flows (secrets)                                    │  │
│   │   - Gmail sync (API credentials)                             │  │
│   │   - LLM processing (Gemini key)                              │  │
│   │   - Calendar sync (API credentials)                          │  │
│   │                                                              │  │
│   │   See docs/api-workflow.md for these endpoints               │  │
│   └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**Why Direct Supabase Access?**
- **No proxy layers** - Reduced latency, simpler architecture
- **RLS enforcement** - Security at database level, consistent across all access paths
- **Native SDKs** - Each platform uses its optimized Supabase client
- **Simpler backend** - Python API is 9 endpoints, not 35

## Authentication

All frontends use Supabase Auth. The authenticated session's JWT is automatically included in queries.

```
// JS
const { data: { session } } = await supabase.auth.getSession()

// Kotlin
supabaseClient.auth.currentSessionOrNull()

// Swift
try await supabase.auth.session
```

---

## Table: `emails`

### List Emails (Paginated)

```sql
SELECT * FROM emails
WHERE is_spam = false AND is_trash = false
ORDER BY date_sent DESC
LIMIT {limit} OFFSET {offset}
```

**JS:**
```javascript
const { data, count, error } = await supabase
  .from('emails')
  .select('*', { count: 'exact' })
  .eq('is_spam', false)
  .eq('is_trash', false)
  .order('date_sent', { ascending: false })
  .range(offset, offset + limit - 1);
```

**Kotlin:**
```kotlin
val emails = supabase.from("emails")
    .select {
        filter { eq("is_spam", false); eq("is_trash", false) }
        order("date_sent", Order.DESCENDING)
        limit(limit)
    }
    .decodeList<Email>()
```

**Swift:**
```swift
let emails: [Email] = try await supabase
    .from("emails")
    .select()
    .eq("is_spam", false)
    .eq("is_trash", false)
    .order("date_sent", ascending: false)
    .range(from: offset, to: offset + limit - 1)
    .execute()
    .value
```

### Get Single Email

```sql
SELECT * FROM emails WHERE id = {emailId}
```

**JS:**
```javascript
const { data, error } = await supabase
  .from('emails')
  .select('*')
  .eq('id', emailId)
  .single();
```

### Optional Filters

| Filter | Query |
|--------|-------|
| Unread only | `.eq('is_unread', true)` |
| Exclude promotions | `.eq('is_promotions', false)` |
| With attachments | `.eq('has_attachments', true)` |

---

## Table: `events`

### List Pending Events (for Review)

```sql
SELECT * FROM events
WHERE status = 'pending_review'
ORDER BY start_datetime ASC
```

**JS:**
```javascript
const { data, error } = await supabase
  .from('events')
  .select('*', { count: 'exact' })
  .eq('status', 'pending_review')
  .order('start_datetime', { ascending: true });
```

### List Events with Filters

```sql
SELECT * FROM events
WHERE status IN ({statuses})
  AND start_datetime >= {startAfter}
  AND start_datetime <= {startBefore}
ORDER BY start_datetime ASC
LIMIT {limit} OFFSET {offset}
```

**JS:**
```javascript
let query = supabase
  .from('events')
  .select('*', { count: 'exact' })
  .order('start_datetime', { ascending: true })
  .range(offset, offset + limit - 1);

if (statuses?.length > 0) {
  query = query.in('status', statuses);
}
if (startAfter) {
  query = query.gte('start_datetime', startAfter);
}
if (startBefore) {
  query = query.lte('start_datetime', startBefore);
}

const { data, count, error } = await query;
```

### Get Event with Sources

```sql
SELECT *, event_sources(*, emails(*))
FROM events
WHERE id = {eventId}
```

**JS:**
```javascript
const { data, error } = await supabase
  .from('events')
  .select(`
    *,
    event_sources(
      *,
      emails(id, subject, from_email, from_name, date_sent)
    )
  `)
  .eq('id', eventId)
  .single();
```

### Update Event Status

```sql
UPDATE events SET status = {status} WHERE id = {eventId}
```

**JS:**
```javascript
const { data, error } = await supabase
  .from('events')
  .update({ status: 'approved' })
  .eq('id', eventId)
  .select()
  .single();
```

### Update Event Details

```javascript
const { data, error } = await supabase
  .from('events')
  .update({
    title: newTitle,
    start_datetime: newStart,
    end_datetime: newEnd,
    location: newLocation,
    description: newDescription
  })
  .eq('id', eventId)
  .select()
  .single();
```

### Event Status Values

| Status | Description |
|--------|-------------|
| `pending_review` | Awaiting user approval |
| `approved` | Approved, ready to sync |
| `syncing` | Currently syncing to calendar |
| `synced` | Successfully synced |
| `sync_failed` | Sync failed |
| `cancelled` | Event was cancelled |
| `rejected` | User rejected event |

---

## Table: `event_sources`

Junction table linking events to contributing emails.

### List Sources for Event

```sql
SELECT *, emails(*) FROM event_sources
WHERE event_id = {eventId}
ORDER BY created_at ASC
```

**JS:**
```javascript
const { data, error } = await supabase
  .from('event_sources')
  .select('*, emails(*)')
  .eq('event_id', eventId)
  .order('created_at', { ascending: true });
```

### Undo Source Contribution

```sql
UPDATE event_sources SET is_undone = true WHERE id = {sourceId}
```

**JS:**
```javascript
const { data, error } = await supabase
  .from('event_sources')
  .update({ is_undone: true })
  .eq('id', sourceId)
  .select()
  .single();
```

### Redo Source Contribution

```javascript
const { data, error } = await supabase
  .from('event_sources')
  .update({ is_undone: false })
  .eq('id', sourceId)
  .select()
  .single();
```

### Key Fields

| Field | Type | Description |
|-------|------|-------------|
| `source_type` | enum | `new_invitation`, `update`, `cancellation`, `reminder`, `unknown` |
| `extracted_data` | JSONB | LLM extraction: `{title, start_datetime, location, description, source_quote}` |
| `event_snapshot_before` | JSON | Previous event state for undo |
| `is_undone` | boolean | Whether contribution is undone |

---

## Table: `integrations`

### List All Integrations

**Important:** Never select `access_token` or `refresh_token` on the frontend.

```sql
SELECT id, user_id, provider, status, provider_email, scopes, last_sync_at, created_at, updated_at
FROM integrations
ORDER BY created_at DESC
```

**JS:**
```javascript
const { data, error } = await supabase
  .from('integrations')
  .select('id, user_id, provider, status, provider_email, scopes, last_sync_at, created_at, updated_at')
  .order('created_at', { ascending: false });
```

### Get Integration by Provider

```javascript
const { data, error } = await supabase
  .from('integrations')
  .select('id, user_id, provider, status, provider_email, scopes, last_sync_at, created_at, updated_at')
  .eq('provider', 'gmail')
  .maybeSingle();  // Returns null if not found (no error)
```

### Check if Provider is Connected

```javascript
const { data } = await supabase
  .from('integrations')
  .select('status')
  .eq('provider', 'gmail')
  .maybeSingle();

const isConnected = data?.status === 'active';
```

### Provider Values

| Provider | Description |
|----------|-------------|
| `gmail` | Gmail email integration |
| `google_photos` | Google Photos (parked; retained for historical rows) |
| `google_calendar` | Google Calendar |

### Status Values

| Status | Description |
|--------|-------------|
| `active` | Working, tokens valid |
| `expired` | Tokens need refresh |
| `revoked` | User revoked access |
| `error` | Integration in error state |

---

## Table: `attachments`

### List Attachments for Email

```sql
SELECT * FROM attachments
WHERE email_id = {emailId}
ORDER BY filename ASC
```

**JS:**
```javascript
const { data, error } = await supabase
  .from('attachments')
  .select('*')
  .eq('email_id', emailId)
  .order('filename', { ascending: true });
```

### Download Attachment

Attachments are stored in Supabase Storage bucket `attachments`.

**JS:**
```javascript
const { data, error } = await supabase
  .storage
  .from('attachments')
  .download(attachment.storage_path);

// data is a Blob
```

---

## Table: `sender_rules`

Automation rules for processing emails from specific senders.

### List Rules

```sql
SELECT * FROM sender_rules
ORDER BY created_at DESC
```

**JS:**
```javascript
const { data, error } = await supabase
  .from('sender_rules')
  .select('*')
  .order('created_at', { ascending: false });
```

### Create Rule

```javascript
const { data, error } = await supabase
  .from('sender_rules')
  .insert({
    sender_domain: 'example.com',  // OR
    sender_email: 'noreply@example.com',
    action: 'auto_approve'  // or 'ignore'
  })
  .select()
  .single();
```

### Delete Rule

```javascript
const { error } = await supabase
  .from('sender_rules')
  .delete()
  .eq('id', ruleId);
```

### Action Values

| Action | Description |
|--------|-------------|
| `auto_approve` | Automatically approve events from sender |
| `ignore` | Ignore all emails from sender |

---

## Table: `user_calendar_settings`

### Get Settings

```javascript
const { data, error } = await supabase
  .from('user_calendar_settings')
  .select('*')
  .maybeSingle();  // Returns null if not set
```

### Update Settings

```javascript
const { data, error } = await supabase
  .from('user_calendar_settings')
  .upsert({
    user_id: userId,  // Required for upsert
    target_calendar_id: calendarId,
    default_invitees: 'spouse@example.com, assistant@example.com'
  })
  .select()
  .single();
```

---

## Table: `jobs`

Background job queue (read-only from frontend).

### List Jobs

```javascript
const { data, count, error } = await supabase
  .from('jobs')
  .select('*', { count: 'exact' })
  .order('created_at', { ascending: false })
  .range(offset, offset + limit - 1);
```

### Get Pending Job Counts

```javascript
const { data, error } = await supabase
  .from('jobs')
  .select('job_type')
  .eq('status', 'pending');

const counts = data.reduce((acc, job) => {
  acc[job.job_type] = (acc[job.job_type] || 0) + 1;
  return acc;
}, {});
```

### Job Status Values

| Status | Description |
|--------|-------------|
| `pending` | Waiting to be processed |
| `processing` | Currently running |
| `completed` | Successfully completed |
| `failed` | Failed (may retry) |
| `dead` | Max retries exceeded |

---

## Python API Endpoints (Server-Side Operations)

These operations require server-side secrets and MUST go through the Python API.

### OAuth Flows

```
GET /integrations/gmail/auth?redirect_uri={uri}
  -> Redirects to Google OAuth consent screen (Gmail)

GET /integrations/calendar/auth?redirect_uri={uri}
  -> Redirects to Google OAuth consent screen (Calendar)

GET /integrations/google/callback?code={code}&state={state}
  -> Unified callback for all Google OAuth flows (public endpoint)
```

### Email Sync

```
POST /emails/sync
Body: { "max_results": 50, "fetch_attachments": true }
Response: { "fetched": 10, "saved": 8, "attachments_downloaded": 3 }
```

### Email Processing (LLM)

```
POST /emails/{email_id}/process
Response: { "num_events": 1, "num_new": 1, "num_updated": 0, "event_ids": ["uuid"] }

POST /emails/batch-process
Body: { "max_emails": 10 }
Response: { "num_events": 5, "num_new": 3, "num_updated": 2, "event_ids": [...] }
```

### Calendar Operations

```
GET /calendars
Response: [{ "id": "primary", "name": "My Calendar", "is_primary": true, "is_selected": true }]

POST /events/{event_id}/sync
Response: { "event_id": "uuid", "google_calendar_event_id": "gcal-id", "synced_at": "..." }
```

### Health Check

```
GET /health
Response: { "status": "healthy" }
```

---

## Error Handling

All queries should handle errors gracefully.

**JS Pattern:**
```javascript
try {
  const { data, error } = await supabase.from('emails').select('*');
  if (error) throw error;
  return { data, error: null };
} catch (error) {
  return { data: null, error: parseSupabaseError(error) };
}
```

**Common Supabase Error Codes:**

| Code | Meaning |
|------|---------|
| `PGRST116` | Row not found (single/maybeSingle) |
| `23503` | Foreign key violation |
| `23505` | Unique constraint violation |
| `42501` | RLS policy violation |

---

## RLS Policy Summary

All tables have Row Level Security enabled. Policies automatically filter by `user_id`.

| Table | Select | Insert | Update | Delete |
|-------|--------|--------|--------|--------|
| `users` | Own row | Own row | Own row | - |
| `emails` | Own rows | Own rows | Own rows | Own rows |
| `events` | Own rows | Own rows | Own rows | Own rows |
| `event_sources` | Via event ownership | Via event ownership | Via event ownership | Via event ownership |
| `integrations` | Own rows | Own rows | Own rows | Own rows |
| `attachments` | Own rows | Own rows | Own rows | Own rows |
| `sender_rules` | Own rows | Own rows | Own rows | Own rows |
| `user_calendar_settings` | Own row | Own row | Own row | - |
| `jobs` | Own rows | - | - | - |

---

## Type Definitions

### TypeScript/JSDoc Types

See `frontend/src/lib/types.js` for canonical type definitions.

### Kotlin Data Classes

```kotlin
@Serializable
data class Email(
    val id: String,
    @SerialName("user_id") val userId: String,
    @SerialName("email_provider") val emailProvider: String,
    @SerialName("provider_message_id") val providerMessageId: String,
    val subject: String?,
    @SerialName("from_email") val fromEmail: String?,
    @SerialName("from_name") val fromName: String?,
    @SerialName("date_sent") val dateSent: String?,
    @SerialName("is_unread") val isUnread: Boolean,
    @SerialName("is_spam") val isSpam: Boolean,
    @SerialName("is_trash") val isTrash: Boolean,
    @SerialName("has_attachments") val hasAttachments: Boolean
)

@Serializable
data class CalendarEvent(
    val id: String,
    @SerialName("user_id") val userId: String,
    val title: String,
    @SerialName("start_datetime") val startDatetime: String?,
    @SerialName("end_datetime") val endDatetime: String?,
    @SerialName("all_day") val allDay: Boolean,
    val location: String?,
    val description: String?,
    val status: String
)

@Serializable
data class Integration(
    val id: String,
    @SerialName("user_id") val userId: String,
    val provider: String,
    val status: String,
    @SerialName("provider_email") val providerEmail: String?,
    @SerialName("last_sync_at") val lastSyncAt: String?
)
```

### Swift Codable Structs

```swift
struct Email: Codable {
    let id: UUID
    let userId: UUID
    let emailProvider: String
    let providerMessageId: String
    let subject: String?
    let fromEmail: String?
    let fromName: String?
    let dateSent: Date?
    let isUnread: Bool
    let isSpam: Bool
    let isTrash: Bool
    let hasAttachments: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case userId = "user_id"
        case emailProvider = "email_provider"
        case providerMessageId = "provider_message_id"
        case subject
        case fromEmail = "from_email"
        case fromName = "from_name"
        case dateSent = "date_sent"
        case isUnread = "is_unread"
        case isSpam = "is_spam"
        case isTrash = "is_trash"
        case hasAttachments = "has_attachments"
    }
}

struct CalendarEvent: Codable {
    let id: UUID
    let userId: UUID
    let title: String
    let startDatetime: Date?
    let endDatetime: Date?
    let allDay: Bool
    let location: String?
    let description: String?
    let status: String

    enum CodingKeys: String, CodingKey {
        case id
        case userId = "user_id"
        case title
        case startDatetime = "start_datetime"
        case endDatetime = "end_datetime"
        case allDay = "all_day"
        case location
        case description
        case status
    }
}

struct Integration: Codable {
    let id: UUID
    let userId: UUID
    let provider: String
    let status: String
    let providerEmail: String?
    let lastSyncAt: Date?

    enum CodingKeys: String, CodingKey {
        case id
        case userId = "user_id"
        case provider
        case status
        case providerEmail = "provider_email"
        case lastSyncAt = "last_sync_at"
    }
}
```
