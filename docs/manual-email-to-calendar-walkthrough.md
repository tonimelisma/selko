# Manual Email-to-Calendar Walkthrough

This guide walks through the complete email-to-calendar event flow using CLI tools, with verification at each step.

## Prerequisites

### 1. Local Supabase Running

```bash
supabase start
```

Verify Supabase is running:
```bash
supabase status
```

### 2. Environment Variables

Ensure your `.env` file contains:

```bash
# Supabase connection
SUPABASE_URL=http://localhost:54321
SUPABASE_ANON_KEY=<your-anon-key>

# Gemini API (for LLM event extraction)
GEMINI_API_KEY=<your-api-key>  # Get from https://aistudio.google.com/apikey

# Test user credentials (must exist in Supabase Auth)
TEST_USER_EMAIL=<your-email>
TEST_USER_PASSWORD=<your-password>
```

### 3. Google Cloud OAuth Credentials

1. Download OAuth credentials from [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Save as `cli/credentials.json`
3. Enable Gmail API and Google Calendar API in your Google Cloud project

### 4. Test User Created

Create a test user if needed:

```bash
uv run python -m cli.cli_user create --email your@email.com --password yourpassword
```

### 5. Python Dependencies Installed

```bash
uv sync
```

---

## Step-by-Step Walkthrough

### Step 1: Gmail OAuth Authentication

Authenticate with Gmail to allow email fetching.

**Command:**
```bash
uv run python -m cli.cli_auth_gmail
```

**What happens:**
1. Opens browser for Gmail OAuth consent
2. User grants Gmail read access
3. OAuth token stored in `integrations` table

**Verification:**
```sql
-- Run in Supabase SQL Editor or via psql
SELECT id, provider, provider_email, created_at
FROM integrations
WHERE provider = 'gmail';
```

Expected output: One row with `provider='gmail'` and your Gmail address.

---

### Step 2: Google Calendar OAuth Authentication

Authenticate with Google Calendar to allow event creation.

**Command:**
```bash
uv run python -m cli.cli_auth_gcal
```

**What happens:**
1. Opens browser for Calendar OAuth consent
2. User grants Calendar read/write access
3. OAuth token stored in `integrations` table

**Verification:**
```sql
SELECT id, provider, created_at
FROM integrations
WHERE provider = 'google_calendar';
```

Expected output: One row with `provider='google_calendar'`.

---

### Step 3: Fetch Emails from Gmail

Fetch recent emails from your Gmail inbox.

**Command:**
```bash
uv run python -m cli.cli_fetch_emails --max 5 --fetch-attachments
```

**Options:**
- `--max N`: Number of emails to fetch (default: 10)
- `--fetch-attachments`: Also download email attachments

**What happens:**
1. Fetches recent emails from Gmail inbox
2. Stores in `emails` table with `processing_status='pending'`
3. Optionally stores attachments in Supabase Storage

**Verification:**
```sql
SELECT id, subject, from_email, processing_status, date_sent
FROM emails
ORDER BY date_sent DESC
LIMIT 10;
```

Expected output: Your fetched emails with `processing_status='pending'`.

---

### Step 4: Preview Event Extraction (Optional)

Preview what events Gemini LLM would extract without saving to database.

**Command:**
```bash
# Preview extraction from recent emails
uv run python -m cli.cli_extract_events --recent 5

# Preview extraction from specific email
uv run python -m cli.cli_extract_events --email-id <uuid>

# Test with fixture data
uv run python -m cli.cli_extract_events --fixture event_birthday_party.json
```

**What happens:**
- Shows what events would be extracted
- Does NOT save to database (preview only)
- Useful for debugging/testing before committing

**Note:** For actual event creation, use `cli_process_emails` (next step).

---

### Step 5: Process Emails into Events

Process emails and save extracted events to the database.

**Commands:**
```bash
# Process a single email by ID
uv run python -m cli.cli_process_emails --email-id <uuid>

# Batch process recent pending emails
uv run python -m cli.cli_process_emails --recent 5
```

**What happens:**
1. Fetches email text and attachments from database
2. Calls Gemini LLM to extract calendar events
3. Deduplicates against existing events (same date + LLM comparison)
4. Creates new events or updates existing ones
5. Links events to source emails in `event_sources` table
6. Marks email as `processed`

**Verification:**
```sql
-- Check extracted events
SELECT id, title, start_datetime, status
FROM events
WHERE status = 'pending_review'
ORDER BY created_at DESC;

-- Check email processing status
SELECT id, subject, processing_status
FROM emails
ORDER BY date_sent DESC
LIMIT 5;

-- Check event-email links
SELECT es.id, e.title, em.subject, es.source_type
FROM event_sources es
JOIN events e ON es.event_id = e.id
JOIN emails em ON es.email_id = em.id
ORDER BY es.created_at DESC
LIMIT 10;
```

---

### Step 6: Review Pending Events

List events waiting for human approval.

**Command:**
```bash
uv run python -m cli.cli_events new
```

**Output shows:**
- Event ID (first 8 chars)
- Title
- Start time
- Location

---

### Step 7: Approve Events

Approve events for calendar sync.

**Command:**
```bash
uv run python -m cli.cli_events approve <event-id>
```

**What happens:**
- Updates event status from `pending_review` to `approved`
- Event ID can be partial (first 8 chars)

**Verification:**
```sql
SELECT id, title, status
FROM events
WHERE id LIKE '<event-id>%';
```

---

### Step 8: Sync to Google Calendar

Sync approved events to your Google Calendar.

**Commands:**
```bash
# Sync single event
uv run python -m cli.cli_events sync <event-id>

# Sync all approved events
uv run python -m cli.cli_events sync_all
```

**What happens:**
1. Creates event in Google Calendar
2. Updates `events` table: `status='synced'`, sets `google_calendar_event_id`
3. Records sync in `calendar_sync_log` table

**Verification:**
```sql
-- Check event sync status
SELECT id, title, status, google_calendar_event_id, synced_at
FROM events
WHERE id LIKE '<event-id>%';

-- Check sync log
SELECT * FROM calendar_sync_log
WHERE event_id LIKE '<event-id>%';
```

**Manual verification:** Open [Google Calendar](https://calendar.google.com) in browser to see the event.

---

## Additional CLI Commands

### Calendar Management

```bash
# List available Google Calendars
uv run python -m cli.cli_calendars list

# Set target calendar for event sync
uv run python -m cli.cli_calendars set <calendar-id>

# Set default invitees for all events
uv run python -m cli.cli_calendars invitees "email1@example.com,email2@example.com"

# View current calendar settings
uv run python -m cli.cli_calendars settings
```

### Sender Rules

```bash
# Auto-approve all events from a domain
uv run python -m cli.cli_events approve_sender school.edu

# Auto-approve all events from specific email
uv run python -m cli.cli_events approve_sender calendar@school.edu

# Ignore all events from a sender
uv run python -m cli.cli_events ignore_sender newsletter@school.edu

# List all sender rules
uv run python -m cli.cli_events list_rules
```

### Event Management

```bash
# List approved/synced events
uv run python -m cli.cli_events approved

# View change log (updates, cancellations)
uv run python -m cli.cli_events updates

# Reject an event
uv run python -m cli.cli_events reject <event-id>

# Restore a rejected event
uv run python -m cli.cli_events restore <event-id>
```

---

## Database Tables Reference

| Table | Purpose |
|-------|---------|
| `integrations` | OAuth tokens for Gmail/Calendar |
| `emails` | Fetched email records |
| `attachments` | Email attachment metadata and storage paths |
| `events` | Extracted calendar events |
| `event_sources` | Links events to source emails |
| `sender_rules` | Auto-approve/ignore rules by sender |
| `calendar_sync_log` | Audit trail of calendar syncs |
| `calendar_settings` | User calendar preferences |

---

## Event Status Lifecycle

```
pending_review  →  approved  →  synced
      ↓               ↓
   rejected      sync_failed
      ↓
  (restore)
      ↓
pending_review
```

---

## Troubleshooting

### OAuth Token Expired

**Symptom:** "Invalid credentials" or "Token expired" error

**Solution:** Re-run the OAuth CLI:
```bash
uv run python -m cli.cli_auth_gmail      # For Gmail
uv run python -m cli.cli_auth_gcal       # For Calendar
```

### No Events Extracted

**Symptom:** Email processed but no events found

**Possible causes:**
1. Email doesn't contain calendar-relevant content
2. Content is in an unsupported format

**Debug steps:**
```bash
# Preview extraction with verbose logging
uv run python -m cli.cli_extract_events -v --email-id <uuid>

# Test with known fixture
uv run python -m cli.cli_extract_events --fixture event_birthday_party.json
```

### Sync Fails with 404

**Symptom:** "Calendar event not found" error during sync

**Cause:** Event was manually deleted from Google Calendar

**Solution:** Event will be automatically recreated on next sync attempt.

### Missing GEMINI_API_KEY

**Symptom:** "GEMINI_API_KEY not configured" error

**Solution:**
1. Get API key from https://aistudio.google.com/apikey
2. Add to `.env`: `GEMINI_API_KEY=your-key-here`

### Authentication Failed

**Symptom:** "TEST_USER_EMAIL and TEST_USER_PASSWORD must be configured" error

**Solution:** Ensure `.env` contains:
```bash
TEST_USER_EMAIL=your@email.com
TEST_USER_PASSWORD=yourpassword
```

### Duplicate Events

**Symptom:** Same event appears multiple times

**Cause:** Deduplication may have failed if events have different dates

**Debug:**
```sql
-- Check for potential duplicates
SELECT title, start_datetime, COUNT(*)
FROM events
GROUP BY title, start_datetime
HAVING COUNT(*) > 1;
```

---

## Quick Reference

| Step | Command | Purpose |
|------|---------|---------|
| 1 | `cli_auth_gmail` | Authenticate with Gmail |
| 2 | `cli_auth_gcal` | Authenticate with Google Calendar |
| 3 | `cli_fetch_emails --max 5` | Fetch emails |
| 4 | `cli_extract_events --recent 5` | Preview extraction (optional) |
| 5 | `cli_process_emails --recent 5` | Process and save events |
| 6 | `cli_events new` | Review pending events |
| 7 | `cli_events approve <id>` | Approve event |
| 8 | `cli_events sync <id>` | Sync to Google Calendar |
