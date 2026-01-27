# Manual API Workflow

This document demonstrates complete manual control of the Selko system via REST API, step-by-step from registration to calendar sync.

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

## Step 1: Register and Login

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

## Step 2: Connect Gmail (OAuth)

```bash
# Initiate OAuth flow (opens browser)
curl -X GET "http://localhost:8000/integrations/gmail/auth" \
  -H "Authorization: Bearer $TOKEN"

# This redirects to Google consent screen
# After you approve, Google redirects back to /integrations/gmail/callback
# Callback automatically saves credentials to database

# Verify integration connected
curl -X GET "http://localhost:8000/integrations/gmail" \
  -H "Authorization: Bearer $TOKEN"
```

## Step 3: Fetch Emails

```bash
# Manually fetch emails from Gmail (with attachments)
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

## Step 4: List Emails

```bash
# List synced emails
curl -X GET "http://localhost:8000/emails?limit=10" \
  -H "Authorization: Bearer $TOKEN"

# Get specific email
EMAIL_ID=$(curl -s "http://localhost:8000/emails" \
  -H "Authorization: Bearer $TOKEN" | jq -r '.items[0].id')

curl -X GET "http://localhost:8000/emails/$EMAIL_ID" \
  -H "Authorization: Bearer $TOKEN"
```

## Step 5: Process Email (Extract Events)

```bash
# Extract events from specific email using LLM
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

## Step 6: Review Pending Events

```bash
# List events pending approval
curl -X GET "http://localhost:8000/events/new" \
  -H "Authorization: Bearer $TOKEN"

# Get event details with source emails
EVENT_ID=$(curl -s "http://localhost:8000/events/new" \
  -H "Authorization: Bearer $TOKEN" | jq -r '.[0].id')

curl -X GET "http://localhost:8000/events/$EVENT_ID" \
  -H "Authorization: Bearer $TOKEN"
```

## Step 7: Approve Event

```bash
# Approve event for calendar sync
curl -X POST "http://localhost:8000/events/$EVENT_ID/approve" \
  -H "Authorization: Bearer $TOKEN"

# Response: {"status": "approved"}
```

## Step 8: Sync to Google Calendar

```bash
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

## Step 9: Download Attachments (Optional)

```bash
# List attachments for email
curl -X GET "http://localhost:8000/emails/$EMAIL_ID/attachments" \
  -H "Authorization: Bearer $TOKEN"

# Download specific attachment
ATTACHMENT_ID=$(curl -s "http://localhost:8000/emails/$EMAIL_ID/attachments" \
  -H "Authorization: Bearer $TOKEN" | jq -r '.[0].id')

curl -X GET "http://localhost:8000/attachments/$ATTACHMENT_ID/download" \
  -H "Authorization: Bearer $TOKEN" \
  --output downloaded_file.pdf
```

## Step 10: List Approved Events

```bash
# View all approved/synced events
curl -X GET "http://localhost:8000/events/approved" \
  -H "Authorization: Bearer $TOKEN"
```

## Complete Journey Summary

1. **Register/Login** - Get JWT token
2. **Connect Gmail** - OAuth flow
3. **Fetch emails** - Downloads to database + storage
4. **Process email** - LLM extracts events
5. **Review events** - View details with sources
6. **Approve event** - Mark ready for sync
7. **Sync to calendar** - Write to Google Calendar
8. **Download attachments** - Retrieve files

This workflow provides full manual control for development, testing, and CLI automation. All endpoints respect Row Level Security (RLS) - users can only access their own data.

## API Documentation

For the complete API reference with all endpoints, request/response schemas, and interactive testing:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
