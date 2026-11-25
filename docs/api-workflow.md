# API Workflow

A walk through the Email → Review → Calendar journey with `curl`, against a
local API. Every call goes to Selko's own API: sign-in, data and the operations
that need provider secrets. The route map is `docs/api-client-endpoints.md`.

## Architecture Overview

```
Browser / curl ── Bearer token ──→ Selko (one process)
                                     ├── /auth/*        sign-in, refresh cookie
                                     ├── data routes    events, emails, settings, …
                                     ├── provider ops   OAuth, sync, LLM, calendar
                                     ├── /live          Server-Sent Events
                                     └── workers        ingestion, extraction,
                                                        calendar writes
                                           │
                                           └── SELKO_DATA_DIR: selko.db + attachments/
```

## Ingestion runs inside the API process

When `ENABLE_BACKGROUND_PROCESSING` is on, the FastAPI lifespan opens the
database (migrating it), releases leases a previous process held
(`selko.db.startup.reset_leases_at_startup`), and starts the ingestion tasks —
coordinator, acquisition, attachments, health floor, calendar mirror — beside
the `WorkerPool` that handles extraction and calendar writes. It stays off
outside production so local servers and tests never poll providers or spend
LLM quota.

Ownership is enforced by leases written under the single writer, with a
generation that fences stale completions; a committed write that creates work
wakes the worker through `WorkSignals`. Newly connected accounts become
pollable automatically (the `integrations_ensure_email_sync_state_*` triggers),
and `request_email_sync_now` brings the next poll forward.

`backend/selko/worker_app.py` runs the same task set as a standalone process
over the same data directory. Never run it while the API's own workers are on:
one process owns the file.

## Start a local API

```bash
cp .env.example .env    # set SELKO_JWT_SECRET (openssl rand -hex 32)
uv run uvicorn selko.api.app:app --port 8000
API=http://localhost:8000
```

`ALLOWED_ORIGINS` must include the origin you send (`-H "Origin: …"`) to the
cookie endpoints.

## Step 1: Sign up and sign in

```bash
curl -s -X POST "$API/auth/signup" -H "Origin: $API" -H 'Content-Type: application/json' \
  -d '{"email":"test@example.com","password":"testpass123"}'

TOKEN=$(curl -s -c cookies.txt -X POST "$API/auth/token" -H "Origin: $API" \
  -H 'Content-Type: application/json' \
  -d '{"grant_type":"password","email":"test@example.com","password":"testpass123"}' \
  | jq -r .access_token)

# Later: a new access token from the refresh cookie (rotates the cookie)
TOKEN=$(curl -s -b cookies.txt -c cookies.txt -X POST "$API/auth/token" -H "Origin: $API" \
  -H 'Content-Type: application/json' -d '{"grant_type":"refresh_token"}' | jq -r .access_token)
```

## Step 2: Connect Google (Gmail + Calendar)

```bash
# One consent screen covers Gmail and Google Calendar
curl -s -H "Authorization: Bearer $TOKEN" "$API/integrations/google/auth" -o /dev/null -w '%{redirect_url}\n'
# Open that URL; Google redirects to /integrations/google/callback, which stores
# the credentials and returns to the web app.

curl -s -H "Authorization: Bearer $TOKEN" "$API/integrations" | jq
```

## Step 3: Fetch mail now

```bash
curl -s -X POST "$API/emails/sync" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"max_results":10,"fetch_attachments":true}'
# {"fetched": 10, "saved": 10, "attachments_downloaded": 3}

curl -s -H "Authorization: Bearer $TOKEN" "$API/emails/history?limit=10" | jq '.items[] | {id, subject}'
```

## Step 4: Extract events

```bash
EMAIL_ID=<id from above>
curl -s -X POST "$API/emails/$EMAIL_ID/process" -H "Authorization: Bearer $TOKEN"
# {"num_events": 2, "num_new": 2, "num_updated": 0, "event_ids": [...]}
# An exhausted daily LLM quota answers 429 and leaves the email as it was.
```

## Step 5: Review

```bash
curl -s -H "Authorization: Bearer $TOKEN" "$API/events/review" | jq
EVENT_ID=<id from the New lane>
curl -s -X POST "$API/events/$EVENT_ID/accept" -H "Authorization: Bearer $TOKEN"
# Changes lane: POST /events/{id}/apply-change or /reject-change
```

Accepting queues a calendar work item; a worker writes it to Google Calendar or
Outlook. `POST /events/{id}/sync` observes or re-queues that worker-owned work;
it never writes to the calendar inline.

## Step 6: Watch it happen

```bash
curl -sN -H "Authorization: Bearer $TOKEN" "$API/live"
# event: ready ... then event: invalidate {"resource": "events", ...} as rows change
```

## Health (no auth)

```bash
curl -s "$API/health" | jq            # status, build_sha, request outcomes
curl -s "$API/health/ingestion" | jq  # tasks, listener, queues
./scripts/check-production-health.sh "$API"
```
