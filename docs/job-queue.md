# Job Queue System

**Architecture**: PostgreSQL-based async job queue with continuous worker pool (no Redis required) following the Async Monolith pattern.

## Overview

The job queue enables automatic background processing without adding external dependencies. It uses:
- **PostgreSQL** for queue storage (Supabase)
- **Worker Pool** with long-running asyncio tasks for job processing
- **APScheduler** for periodic scheduling (cron-like tasks)
- **Atomic job claiming** via `FOR UPDATE SKIP LOCKED`

## Job Types and Data Flow

```
Cron (5 min) -> email_fetch job -> Gmail API -> emails table
                                                 |
                             email_process job -> Gemini LLM -> events table
                                                                 |
User approves event -> calendar_sync job -> Google Calendar API
```

| Job Type | Trigger | Purpose | Creates |
|----------|---------|---------|---------|
| `email_fetch` | Cron (every 5 min) | Fetch emails from Gmail | `email_process` jobs |
| `email_process` | After email stored | Extract events via LLM | Events in `events` table |
| `calendar_sync` | After event approved | Write to Google Calendar | Calendar event ID |

## Database Schema

**`jobs` table**:
- `job_type`: email_fetch, email_process, calendar_sync
- `status`: pending -> processing -> completed/failed/dead
- `payload`: JSONB with job-specific data
- `priority`: Higher = more urgent (default 0)
- `attempts`: Retry counter
- `locked_until`: Prevents duplicate work
- `locked_by`: Worker ID that claimed job

**Key features**:
- Atomic claiming via PostgreSQL function `claim_next_job()`
- Automatic retry on failure (up to `max_attempts`)
- Priority-based ordering
- Lock expiry handling for crashed workers

## Worker Operations

### Job Service (`backend/selko/services/jobs.py`)
- `enqueue_job()` - Create new job
- `claim_job()` - Atomically claim next pending job
- `complete_job()` - Mark job as completed
- `fail_job()` - Handle failure with retry logic
- `get_pending_count()` - Get queue stats

### Worker Pool (`backend/selko/workers/pool.py`)
- Manages N long-running asyncio tasks (default: 3 workers)
- Each worker continuously polls the queue and processes jobs
- Provides immediate job processing (~1 second latency)
- Workers run concurrently for high throughput
- Graceful shutdown ensures current jobs complete

### Configuration
- `WORKER_POOL_SIZE`: Number of concurrent workers (default: 3)
- `WORKER_IDLE_SLEEP_SECONDS`: Sleep time when queue is empty (default: 1.0)
- `WORKER_ERROR_BACKOFF_SECONDS`: Sleep time after errors (default: 5.0)

### Individual Workers
- `email_fetch_worker` - Fetches emails, creates process jobs
- `email_process_worker` - Runs LLM extraction, creates events
- `calendar_sync_worker` - Writes events to Google Calendar (TODO)

## Running Locally

The job queue automatically starts with the FastAPI server:

```bash
# Start local Supabase
supabase start

# Run API server (job queue starts automatically)
uv run python -m selko.api

# Jobs are processed automatically in the background
# Check logs to see job processing
```

## Monitoring Jobs

### API Endpoints

```bash
# Get pending job counts
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/jobs/pending

# List jobs for current user
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/jobs?status=all

# Get specific job status
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/jobs/{job_id}
```

### Direct Database Queries

```sql
-- View all pending jobs
SELECT * FROM jobs WHERE status = 'pending' ORDER BY priority DESC;

-- View failed jobs
SELECT * FROM jobs WHERE status = 'failed' OR status = 'dead';

-- Unlock expired jobs (manual recovery)
SELECT unlock_expired_jobs();
```

## Testing

Integration tests validate the job queue with real Supabase:

```bash
# Run job queue tests
uv run pytest backend/tests/integration/test_integration_jobs.py -v

# Test coverage:
# - Job enqueue and claim
# - Priority ordering
# - Retry logic
# - Lock expiry
# - Concurrent worker safety
```

## Deployment Notes

### Single Instance
The Async Monolith runs as a single process. For MVP, this is sufficient (<10,000 users).

### Performance Characteristics
- **Latency**: Jobs process within ~1 second (vs. 0-10 seconds with polling)
- **Throughput**: 3 concurrent workers x job completion rate
- **Scalability**: Add more workers by increasing `WORKER_POOL_SIZE`

### Horizontal Scaling
When scaling to multiple instances:
- Only ONE instance should run the schedulers (leader election needed)
- Multiple instances can run worker pools (SKIP LOCKED prevents conflicts)
- Consider migrating to pg_cron for scheduling at scale

### Migration Path
- **Start**: PostgreSQL queue + asyncio workers (current, $0/mo)
- **Scale**: Add Redis + ARQ when PostgreSQL queue insufficient ($10+/mo)
- Pattern allows gradual migration without rewriting workers
