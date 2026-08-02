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
expired leases during ordinary `FOR UPDATE SKIP LOCKED` claims; there is no
startup-only unlock step. Provider cursor commits occur after each durable
page, while message acquisition, attachment storage, and downstream LLM work
retry independently.

The old `scheduled_tasks` email-fetch path below remains only as an explicit
rollback compatibility path while v2 is disabled. It must not be enabled at
the same time as v2.

**Architecture**: Status-based workers using PostgreSQL atomic claiming with continuous worker pool (no Redis required) following the Async Monolith pattern.

## Overview

The background processing system uses status-based polling where data tables ARE the queue. Workers poll the data tables directly instead of using a separate job queue table. This provides:
- **Single source of truth**: No job-data synchronization bugs
- **Simpler debugging**: Query data tables directly to see pending work
- **Natural idempotency**: Data state is always consistent

Components:
- **PostgreSQL** for queue storage via data tables (Supabase)
- **Worker Pool** with long-running asyncio tasks for processing
- **Ingestion coordinator** owning its own polling cadence via database leases
- **Atomic claiming** via `FOR UPDATE SKIP LOCKED`

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
email = await claim_pending_email(worker_id)  # Uses FOR UPDATE SKIP LOCKED

# Worker processes
await process_email(email)

# Worker updates status
complete_email_processing(email_id)  # Sets status='processed'
```

**Email statuses**: `pending` → `processing` → `processed` / `failed` / `skipped`

### 2. Event Sync (status-based)

Events with `status='approved'` are automatically synced. Workers claim them directly:

```python
# Worker claims next approved event
event = await claim_approved_event_for_sync(worker_id)  # Uses FOR UPDATE SKIP LOCKED

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

### Claiming Columns (events table)

| Column | Type | Description |
|--------|------|-------------|
| `status` | text | Includes `syncing` state during sync |
| `locked_until` | timestamptz | Lock expiration time |
| `locked_by` | text | Worker ID that claimed this event |
| `sync_attempts` | integer | Number of sync attempts |
| `max_sync_attempts` | integer | Maximum sync attempts (default: 3) |
| `sync_error` | text | Last sync error message |

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

## RPC Functions

Atomic claiming functions using `FOR UPDATE SKIP LOCKED`:

| Function | Purpose |
|----------|---------|
| `claim_unprocessed_email(worker_id, lock_duration)` | Claim next pending email |
| `claim_approved_event(worker_id, lock_duration)` | Claim next approved event |
| `claim_next_scheduled_task(task_types, worker_id, lock_duration)` | Claim next scheduled task |
| `unlock_expired_email_locks()` | Reset stuck email processing |
| `unlock_expired_event_locks()` | Reset stuck event syncing |
| `unlock_expired_scheduled_tasks()` | Reset stuck scheduled tasks |

## Running Locally

The worker system automatically starts with the FastAPI server:

```bash
# Start local Supabase
supabase start

# Run API server (workers start automatically if enabled)
ENABLE_BACKGROUND_PROCESSING=true uv run python -m selko.api

# Work is processed automatically in the background
# Check logs to see processing
```

## Monitoring

### View Pending Work

```sql
-- Pending emails awaiting LLM processing
SELECT id, subject, processing_status, attempts, locked_by
FROM emails
WHERE processing_status = 'pending';

-- Approved events awaiting calendar sync
SELECT id, title, status, sync_attempts, locked_by
FROM events
WHERE status = 'approved';

-- Pending scheduled tasks
SELECT id, task_type, status, scheduled_at
FROM scheduled_tasks
WHERE status = 'pending';
```

### Unlock Stuck Work

```sql
-- Unlock emails stuck in processing
SELECT unlock_expired_email_locks();

-- Unlock events stuck in syncing
SELECT unlock_expired_event_locks();

-- Unlock stuck scheduled tasks
SELECT unlock_expired_scheduled_tasks();
```

## Testing

Integration tests validate the worker system with real Supabase:

```bash
# Run worker tests
uv run pytest backend/tests/integration/test_integration_workers.py -v

# Test coverage:
# - Email status-based claiming
# - Event status-based claiming
# - Scheduled task lifecycle
# - Concurrent worker safety (SKIP LOCKED)
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
When scaling to multiple instances:
- Only ONE instance should run the scheduler (leader election needed)
- Multiple instances can run worker pools (SKIP LOCKED prevents conflicts)
- Consider migrating to pg_cron for scheduling at scale
