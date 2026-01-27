# Server-Side API Workflow

This document demonstrates the Python API endpoints for server-side operations that require secrets (OAuth, Gmail API, LLM, Google Calendar API).

**For data queries** (listing emails, viewing events, updating status), see `supabase-frontend-queries.md` - frontends query Supabase directly.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DATA ACCESS                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   Frontend (Web/Android/iOS)                                        │
│         │                                                            │
│         ├──────────────────────────────────────┐                    │
│         │                                      │                    │
│         ▼                                      ▼                    │
│   ┌──────────────┐                    ┌──────────────────┐          │
│   │   Supabase   │                    │   Python API     │          │
│   │   (Direct)   │                    │   (Server-Side)  │          │
│   └──────────────┘                    └──────────────────┘          │
│         │                                      │                    │
│   Data queries:                         Requires secrets:           │
│   - List emails                         - OAuth flows               │
│   - View events                         - Gmail sync                │
│   - Update status                       - LLM processing            │
│   - Download attachments                - Calendar sync             │
│   - Read integrations                                               │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

```bash
# Start local Supabase
supabase start

# Start API server (in separate terminal)
uv run python -m selko.api

# Get Supabase connection details from supabase start output
SUPABASE_URL="http://localhost:54321"
SUPABASE_ANON_KEY="<from output>"
```

## Step 1: Register and Login (via Supabase Auth)

```bash
# Register new user and save token
curl -X POST "$SUPABASE_URL/auth/v1/signup" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"testpass123"}' \
  | jq -r '.access_token' > token.txt

# OR login if user exists
curl -X POST "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"testpass123"}' \
  | jq -r '.access_token' > token.txt

TOKEN=$(cat token.txt)
```

## Step 2: Connect Gmail (OAuth via Python API)

```bash
# Initiate OAuth flow (redirects to Google consent screen)
curl -X GET "http://localhost:8000/integrations/gmail/auth" \
  -H "Authorization: Bearer $TOKEN" \
  -L  # Follow redirects

# After you approve, Google redirects back to /integrations/gmail/callback
# Callback automatically saves credentials to database

# Verify integration connected (via Supabase direct)
curl "$SUPABASE_URL/rest/v1/integrations?select=provider,status,provider_email" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Authorization: Bearer $TOKEN"
```

## Step 3: Sync Emails (Python API - requires Gmail API credentials)

```bash
# Manually fetch emails from Gmail
curl -X POST "http://localhost:8000/emails/sync" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_results":10,"fetch_attachments":true}'

# Response:
# {
#   "fetched": 10,
#   "saved": 10,
#   "attachments_downloaded": 3
# }
```

## Step 4: List Synced Emails (via Supabase direct)

```bash
# List emails (direct Supabase query)
curl "$SUPABASE_URL/rest/v1/emails?select=id,subject,from_email,date_sent&order=date_sent.desc&limit=10" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Authorization: Bearer $TOKEN"

# Get specific email
EMAIL_ID="<uuid from above>"
curl "$SUPABASE_URL/rest/v1/emails?id=eq.$EMAIL_ID" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Authorization: Bearer $TOKEN"
```

## Step 5: Process Email with LLM (Python API - requires Gemini API key)

```bash
# Extract events from specific email
curl -X POST "http://localhost:8000/emails/$EMAIL_ID/process" \
  -H "Authorization: Bearer $TOKEN"

# Response:
# {
#   "num_events": 2,
#   "num_new": 2,
#   "num_updated": 0,
#   "event_ids": ["uuid1", "uuid2"]
# }

# OR process multiple recent emails
curl -X POST "http://localhost:8000/emails/batch-process" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_emails":5}'
```

## Step 6: Review and Approve Events (via Supabase direct)

```bash
# List pending events (direct Supabase query)
curl "$SUPABASE_URL/rest/v1/events?status=eq.pending_review&select=*" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Authorization: Bearer $TOKEN"

# Get event with sources
EVENT_ID="<uuid from above>"
curl "$SUPABASE_URL/rest/v1/events?id=eq.$EVENT_ID&select=*,event_sources(*,emails(id,subject,from_email))" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Authorization: Bearer $TOKEN"

# Approve event (direct Supabase update)
curl -X PATCH "$SUPABASE_URL/rest/v1/events?id=eq.$EVENT_ID" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"approved"}'
```

## Step 7: Sync to Google Calendar (Python API - requires Calendar API credentials)

```bash
# List available calendars
curl -X GET "http://localhost:8000/calendars" \
  -H "Authorization: Bearer $TOKEN"

# Response:
# [{"id": "primary", "name": "My Calendar", "is_primary": true}]

# Sync approved event to Google Calendar
curl -X POST "http://localhost:8000/events/$EVENT_ID/sync" \
  -H "Authorization: Bearer $TOKEN"

# Response:
# {
#   "event_id": "uuid",
#   "google_calendar_event_id": "google_event_id",
#   "synced_at": "2026-01-26T12:00:00Z",
#   "status": "synced"
# }
```

## Complete Journey Summary

| Step | Action | Endpoint |
|------|--------|----------|
| 1 | Register/Login | Supabase Auth (direct) |
| 2 | Connect Gmail | Python API: `GET /integrations/gmail/auth` |
| 3 | Sync emails | Python API: `POST /emails/sync` |
| 4 | List emails | Supabase (direct) |
| 5 | Process with LLM | Python API: `POST /emails/{id}/process` |
| 6 | Review/approve | Supabase (direct) |
| 7 | Sync to calendar | Python API: `POST /events/{id}/sync` |

## Python API Endpoints Reference

### Health Endpoints (no auth)

```
GET /health
Response: {"status": "ok"}

GET /health/db
Response: {"status": "ok", "database": "connected"}
```

### OAuth Endpoints

```
GET /integrations/gmail/auth
  Requires: Bearer token
  Returns: Redirect to Google OAuth consent screen

GET /integrations/gmail/callback?code={code}&state={state}
  Public endpoint (no auth required)
  Returns: {"status": "success", "provider_email": "user@gmail.com"}
```

### Email Sync/Process Endpoints

```
POST /emails/sync
  Requires: Bearer token, Gmail integration
  Body: {"max_results": 50, "fetch_attachments": true}
  Returns: {"fetched": 10, "saved": 8, "attachments_downloaded": 3}

POST /emails/{email_id}/process
  Requires: Bearer token
  Returns: {"num_events": 1, "num_new": 1, "num_updated": 0, "event_ids": ["uuid"]}

POST /emails/batch-process
  Requires: Bearer token
  Body: {"max_emails": 10}
  Returns: {"num_events": 5, "num_new": 3, "num_updated": 2, "event_ids": [...]}
```

### Calendar Endpoints

```
GET /calendars
  Requires: Bearer token, Google Calendar integration
  Returns: [{"id": "primary", "name": "My Calendar", "is_primary": true}]

POST /events/{event_id}/sync
  Requires: Bearer token
  Returns: {"event_id": "uuid", "google_calendar_event_id": "gcal-id", "synced_at": "..."}
```

## Data Queries (Direct Supabase)

For all data operations (listing, filtering, updating), query Supabase directly using the native SDK for your platform:

- **Web (JavaScript)**: `@supabase/supabase-js`
- **Android (Kotlin)**: `io.github.jan-tennert.supabase`
- **iOS (Swift)**: `supabase-swift`

See `supabase-frontend-queries.md` for canonical query patterns.
