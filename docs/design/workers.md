GOVERNS: backend/selko/workers/** backend/selko/services/email_ingestion.py backend/selko/db/email_sync.py backend/selko/db/emails.py backend/selko/db/calendar_work.py

# Status-Based Worker System

## Durable email polling v2

Email discovery runs inside the API process whenever
`ENABLE_BACKGROUND_PROCESSING` is on, started from the FastAPI lifespan via
`IngestionRuntime` alongside the `WorkerPool`. It is the only ingestion path —
the `email_fetch` scheduled task and its APScheduler job were removed, so
`scheduled_tasks` now carries `photo_fetch` only. The standalone
`uv run python -m selko.worker_app` entry point runs the same task set for local
drills or a future dedicated service.

The v2 path uses `email_sync_state` leases for one active integration, records
each run in `email_sync_runs`, and writes immutable provider identities to
`email_ingestion_items` before acquiring bodies or attachments. Claims reclaim
expired leases during ordinary claims (each claim is one write transaction
under the single writer); there is no periodic unlock sweep. Provider cursor commits occur after each durable
page, while message acquisition, attachment storage, and downstream LLM work
retry independently.

**Architecture**: Status-based workers claiming rows from the SQLite data tables, in one process with the API (no Redis, no separate worker service). Work is announced by `selko.db.bus.WorkSignals`: a committed write that creates work wakes the worker that should take it, and a slow safety-net poll is the floor.

## Overview

The background processing system uses status-based polling where data tables ARE the queue. Workers poll the data tables directly instead of using a separate job queue table. This provides:
- **Single source of truth**: No job-data synchronization bugs
- **Simpler debugging**: Query data tables directly to see pending work
- **Natural idempotency**: Data state is always consistent

Components:
- **SQLite** data tables as the queue (`selko.db`)
- **Worker Pool** with long-running asyncio tasks for processing
- **Ingestion coordinator** owning its own polling cadence via database leases
- **Atomic claiming**: one `db.write()` transaction per claim, serialized by the single writer; leases carry a generation that fences stale completions

## Data Flow

```
Coordinator (60s tick) -> provider discovery -> emails table (status=pending)
                                                 |
                               Worker claims email -> Gemini LLM -> events table (status=pending_review)
                                                                     |
User approves event -> status='approved' -> Worker claims event -> Google Calendar API -> status='synced'
```

Clients do not write to Google Calendar after approval. The worker pool is the
single owner of calendar writes. `POST /events/{id}/sync` is an idempotent
queue/retry endpoint: it accepts `approved`, `syncing`, and `synced` as current
states, and resets an exhausted `sync_failed` event to `approved` with a fresh
attempt budget. It never performs the Google write inline.

## How It Works

### 1. Email Processing (status-based)

Emails are stored with `processing_status='pending'`. Workers claim them directly:

```python
# Worker claims next pending email
email = claim_unprocessed_email(db, worker_id, lock_seconds)  # selko.db.emails

# Worker processes; the claim increments lock_generation on every lease.
await process_email(email)

# The fenced extraction commit writes all event/source decisions and sets the
# terminal email status in the same transaction.
commit_email_extraction(email_id, worker_id, lock_generation, decisions, "processed")
```

**Email statuses**: `pending` → `processing` → `processed` / `failed` / `skipped`

Each extracted-event decision includes the local-day candidate window and its
fingerprint. `selko.db.events.commit_email_extraction` rechecks the MD5 of
sorted `id:updated_at` rows inside its write transaction. A changed band
returns a conflict with no writes; Python rereads and recomputes up to three
times. No lock is held during provider or LLM I/O, so extraction remains
parallel.

### 2. Event Sync (status-based)

Events with `status='approved'` are automatically synced. Workers claim them directly:

```python
# Worker claims next approved event
event = await claim_approved_event_for_sync(pool, worker_id)  # selko.db.calendar_work

# Worker syncs to Google Calendar
quota = QuotaService(client).check_and_increment(event["user_id"], "calendar_syncs")
if not quota.allowed:
    defer_event_sync_for_quota(event, quota.resets_at)
    return

google_event_id = await sync_event(event)

# Worker updates status
complete_event_sync(event_id, google_event_id)  # Sets status='synced'
```

**Event statuses**: `pending_review` → `approved` → `syncing` → `synced` / `sync_failed`

The calendar quota is enforced by the worker that owns the external write. A
quota deferral releases the lock, restores the claim's attempt budget, and sets
`next_retry_at` to the daily reset rather than consuming a failed sync attempt.

### 3. Scheduled Tasks (photo_fetch only)

`scheduled_tasks` now carries only photo work. Email discovery deliberately does
**not** use this table: a timer row stuck in `processing` used to suppress a
provider indefinitely, which is why email ingestion moved to `email_sync_state`
leases that expire and are reclaimed during ordinary claims.

```python
enqueue_scheduled_task(user_id, "photo_fetch", {...})

task = await claim_scheduled_task(["photo_fetch"], worker_id)
await process_photo_fetch_task(task)
complete_scheduled_task(task_id)
```

## Database Schema

### Claiming Columns (emails table)

| Column | Type | Description |
|--------|------|-------------|
| `processing_status` | text | `pending`, `processing`, `processed`, `failed`, `skipped` |
| `locked_until` | timestamptz | Lock expiration time |
| `locked_by` | text | Worker ID that claimed this email |
| `attempts` | integer | Number of processing attempts |
| `max_attempts` | integer | Maximum attempts (default: 3) |

### Calendar Work Items (`calendar_work_items` table)

| Column | Type | Description |
|--------|------|-------------|
| `status` | text | `pending`, `processing`, `succeeded`, `failed`, `blocked`, or `superseded` |
| `action` | text | `upsert` or `cancel` |
| `generation` | bigint | Monotonic provider-write fence |
| `locked_until` / `locked_by` | timestamptz / text | Crash-safe worker lease |
| `attempts` / `max_attempts` | integer | Retry budget |
| `failure_code` / `failure_detail` | text | Typed failure and operator detail |

### Scheduled Tasks Table

Only for periodic tasks (currently just `photo_fetch`):

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid | Task ID |
| `user_id` | uuid | Owner user |
| `task_type` | text | Only `photo_fetch` currently |
| `payload` | jsonb | Task-specific data |
| `status` | text | `pending`, `processing`, `completed`, `failed` |
| `scheduled_at` | timestamptz | When to run |
| `locked_until` | timestamptz | Lock expiration |
| `locked_by` | text | Worker ID |

## Worker Pool (`backend/selko/workers/pool.py`)

The worker pool polls three sources in priority order:

```python
async def _process_any_work(self, worker_id: str) -> bool:
    # 1. Scheduled tasks (photo_fetch)
    task = await claim_scheduled_task(["photo_fetch"], worker_id)
    if task: return await self._process_scheduled_task(task)

    # 2. Pending emails
    email = await claim_pending_email(worker_id)
    if email: return await self._process_email(email)

    # 3. Approved events
    event = await claim_approved_event_for_sync(worker_id)
    if event: return await self._process_event_sync(event)

    return False
```

### Configuration

- `WORKER_POOL_SIZE`: Number of concurrent workers (default: 3)
- `WORKER_IDLE_SLEEP_SECONDS`: Sleep time when no work available (default: 1.0)
- `WORKER_ERROR_BACKOFF_SECONDS`: Sleep time after errors (default: 5.0)

## Claim functions

Python functions in `backend/selko/db/`:

| Function | Purpose |
|----------|---------|
| `emails.claim_unprocessed_email(db, worker_id, lock_duration_seconds)` | Reclaim one expired lease, then claim the oldest claimable email |
| `emails.fail_email_processing(...)` | Fenced retry-or-terminate for a claimed email |
| `calendar_work.claim_calendar_work_item(db, worker_id, lease_seconds, providers)` | Claim the next calendar work item whose provider is writable; returns `(item, event)` |
| `calendar_work.complete_calendar_work(...)` / `fail_calendar_work(...)` | Fenced completion of a calendar work item |
| `email_sync.claim_due_email_sync(...)` and the acquisition/attachment claims | Provider discovery and acquisition leases |
| `startup.reset_leases_at_startup(db)` | Release every lease a previous process held, before workers start |

## Running Locally

The worker system automatically starts with the FastAPI server:

```bash
# Run API server (workers start automatically if enabled; data in SELKO_DATA_DIR)
ENABLE_BACKGROUND_PROCESSING=true uv run uvicorn selko.api.app:app --port 8000

# Work is processed automatically in the background
# Check logs to see processing
```

## Monitoring

### View Pending Work

`/health/ingestion` and `/health` report counts. To look at rows, open the file
read-only: `sqlite3 -readonly "file:$SELKO_DATA_DIR/selko.db?mode=ro"`.

```sql
-- Pending emails awaiting LLM processing
SELECT id, subject, processing_status, attempts, locked_by
FROM emails
WHERE processing_status = 'pending';

-- Calendar work awaiting or undergoing provider sync
SELECT id, event_id, action, status, attempts, max_attempts, locked_by
FROM calendar_work_items
WHERE status IN ('pending', 'processing')
ORDER BY created_at;

-- Pending scheduled tasks
SELECT id, task_type, status, scheduled_at
FROM scheduled_tasks
WHERE status = 'pending';
```

### Stuck work

An expired lease is reclaimed by the next claim, and leases held by a previous
process are released at startup (`selko.db.startup.reset_leases_at_startup`)
before any worker starts. There is no manual unlock step.

## Testing

Integration tests validate the worker system over a real SQLite file:

```bash
# Run worker tests
uv run pytest backend/tests/integration/test_integration_workers.py -v

# Test coverage:
# - Email status-based claiming
# - Event status-based claiming
# - Scheduled task lifecycle
# - Concurrent worker safety (single writer, generation fences)
# - Lock expiry recovery
# - Retry logic
```

## Key Differences from Job Queue

| Aspect | Old (Job Queue) | New (Status-Based) |
|--------|-----------------|-------------------|
| Queue location | Separate `jobs` table | Data tables directly |
| Email processing | Job with `{email_id}` payload | Claim email by `processing_status='pending'` |
| Calendar sync | Job with `{event_id}` payload | Claim event by `status='approved'` |
| Debugging | Check jobs table + data table | Check data table only |
| Synchronization | Must keep job and data in sync | Data IS the queue |

## Deployment Notes

### Single Instance
The Async Monolith runs as a single process. For MVP, this is sufficient (<10,000 users).

### Performance Characteristics
- **Latency**: Work processes within ~1 second
- **Throughput**: 3 concurrent workers x completion rate
- **Scalability**: Add more workers by increasing `WORKER_POOL_SIZE`

### Horizontal Scaling
One process owns the database file. Running a second instance against the same
file is not supported; scale by giving the one process more concurrency.
