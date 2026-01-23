# Simplified Tech Stack - Reality Check

**Date:** 2026-01-22
**Context:** Pushing back on feature creep, keeping it simple

## What You Actually Need (vs What I Recommended)

### My Original Recommendation (Overkill)
```
FastAPI + ARQ + Redis + Upstash + APScheduler + Fly.io
```
**Complexity:** 6 moving parts
**Monthly cost:** $0-10 (POC), $40-60 (MVP)

### What You Actually Need (Right-sized)
```
FastAPI + Supabase (database + storage + auth)
```
**Complexity:** 2 parts (you already have Supabase!)
**Monthly cost:** $0 (POC), $25-40 (MVP)

---

## What Supabase Already Provides

Supabase is **way more** than just a database. You already have:

| Feature | What It Is | Do You Need Redis? |
|---------|------------|-------------------|
| **PostgreSQL** | Full-featured database | ❌ No |
| **Supabase Storage** | Object storage (like S3) | ❌ No |
| **Supabase Auth** | User authentication + RLS | ❌ No |
| **Realtime** | WebSocket pub/sub (PostgreSQL changes) | ❌ No |
| **Edge Functions** | Serverless functions (Deno) | ❌ No (can run background jobs!) |
| **pg_cron** | Built-in cron scheduler | ❌ No (can replace APScheduler!) |
| **PostgreSQL queues** | Table-based job queue or LISTEN/NOTIFY | ❌ No (can replace Redis!) |

**You already paid for (or have free access to) all of this.**

---

## Reality Check: Do You Need a Job Queue?

### Ask Yourself:
1. **How many background jobs do you have?**
   - POC: Zero (just CLI scripts)
   - MVP: Maybe email fetching, attachment processing

2. **What's the volume?**
   - POC: A few emails per hour
   - MVP: Maybe 100-1000 emails per day

3. **Do you need distributed workers?**
   - POC: No (single process is fine)
   - MVP: Probably no (single Fly.io instance handles 1000s of requests)

4. **Do you need advanced features?** (retries, priorities, scheduling, monitoring)
   - POC: No
   - MVP: Maybe simple retries

### The Truth:
**You probably don't need Redis/ARQ at all.** Certainly not for POC, maybe not even for MVP.

---

## Simplified Stack Options

### Option 1: Bare Minimum (Start Here) ⭐ RECOMMENDED

**Stack:**
```
FastAPI + Supabase
```

**Architecture:**
```
┌─────────────────┐
│   FastAPI App   │  ← REST APIs
│   (Fly.io)      │     Background tasks run in-process
└────────┬────────┘
         │
         └─→ Supabase (PostgreSQL + Storage + Auth)
```

**Background Jobs:** Just use FastAPI `BackgroundTasks`
```python
from fastapi import BackgroundTasks

@app.post("/emails/fetch")
async def fetch_emails(background_tasks: BackgroundTasks):
    # Trigger background job (runs in-process, non-blocking)
    background_tasks.add_task(fetch_emails_from_gmail)
    return {"status": "fetching"}

async def fetch_emails_from_gmail():
    # Your existing logic from CLI
    # Runs async, doesn't block the response
    pass
```

**Polling/Cron:** Use Supabase pg_cron (built-in!)
```sql
-- Schedule email fetch every 5 minutes
SELECT cron.schedule(
    'fetch-emails',
    '*/5 * * * *',
    $$
    SELECT net.http_post(
        url := 'https://selko-api.fly.dev/cron/fetch-emails',
        headers := '{"Authorization": "Bearer SECRET"}'::jsonb
    );
    $$
);
```

**Pros:**
- ✅ Zero additional infrastructure
- ✅ No Redis to manage
- ✅ FastAPI BackgroundTasks for simple jobs
- ✅ pg_cron for scheduling (built into Supabase)
- ✅ Simplest possible

**Cons:**
- ⚠️ Long-running tasks block process (but async helps)
- ⚠️ No job queue (retry logic is manual)
- ⚠️ Single point of failure (but fine for POC/MVP)

**When This Breaks:**
- When a single task takes >30 seconds
- When you need guaranteed job execution (retries)
- When you need distributed workers

**Cost:** $0 (Supabase free) + $0 (Fly.io free tier) = **$0/month**

---

### Option 2: PostgreSQL-Based Queue (No Redis)

**Stack:**
```
FastAPI + PostgreSQL Queue (pgmq or simple table) + Supabase
```

**What:** Use PostgreSQL as your job queue (no Redis needed!)

**How:** Use Supabase's PostgreSQL for queuing:

**Option 2a: Simple Table-Based Queue**
```sql
-- Create jobs table
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT DEFAULT 'pending',
    attempts INT DEFAULT 0,
    max_attempts INT DEFAULT 3,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    scheduled_for TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

CREATE INDEX idx_jobs_pending ON jobs(status, scheduled_for)
WHERE status = 'pending';
```

```python
# Enqueue job
await client.table('jobs').insert({
    'job_type': 'fetch_emails',
    'payload': {'user_id': user_id}
}).execute()

# Worker (simple polling)
async def process_jobs():
    while True:
        # Get next job
        result = await client.table('jobs')\
            .select('*')\
            .eq('status', 'pending')\
            .lte('scheduled_for', 'now()')\
            .order('created_at')\
            .limit(1)\
            .execute()

        if result.data:
            job = result.data[0]
            # Process job...
            # Update status to 'completed' or 'failed'

        await asyncio.sleep(5)  # Poll every 5 seconds
```

**Option 2b: PostgreSQL LISTEN/NOTIFY**
```sql
-- Trigger notification on new job
CREATE FUNCTION notify_new_job() RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('new_job', NEW.id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER jobs_notify AFTER INSERT ON jobs
FOR EACH ROW EXECUTE FUNCTION notify_new_job();
```

```python
# Worker listens for notifications (real-time, no polling!)
import asyncpg

conn = await asyncpg.connect(database_url)
await conn.add_listener('new_job', handle_job)
```

**Option 2c: Use PGMQ (PostgreSQL Message Queue)**
```sql
-- Install pgmq extension (if available on Supabase)
CREATE EXTENSION pgmq;

-- Create queue
SELECT pgmq.create('email_jobs');

-- Enqueue
SELECT pgmq.send('email_jobs', '{"user_id": "123"}');

-- Dequeue
SELECT * FROM pgmq.read('email_jobs', 30, 1);
```

**Pros:**
- ✅ No Redis needed
- ✅ Use existing Supabase PostgreSQL
- ✅ Transactional guarantees
- ✅ Simple retry logic (attempt counter)
- ✅ Free (no extra service)

**Cons:**
- ⚠️ More code to write (vs ARQ)
- ⚠️ PostgreSQL not optimized for queues (vs Redis)
- ⚠️ Need to implement worker polling

**When This Breaks:**
- When you need 1000s of jobs/second (PostgreSQL won't scale)
- When you need complex routing/priorities

**Cost:** $0 (uses Supabase) + $0 (Fly.io free tier) = **$0/month**

---

### Option 3: Supabase Edge Functions (Serverless Background Jobs)

**Stack:**
```
FastAPI + Supabase Edge Functions + Supabase
```

**What:** Use Supabase's built-in Edge Functions for background jobs (Deno serverless)

**How:**
```typescript
// supabase/functions/fetch-emails/index.ts
import { serve } from "https://deno.land/std@0.168.0/http/server.ts"

serve(async (req) => {
  // Your email fetching logic here
  // Runs serverless, scales to zero
  const { userId } = await req.json()

  // Call Gmail API, store in Supabase

  return new Response(JSON.stringify({ status: 'done' }), {
    headers: { "Content-Type": "application/json" },
  })
})
```

**Deploy:**
```bash
supabase functions deploy fetch-emails
```

**Trigger from FastAPI:**
```python
# Invoke edge function (non-blocking)
response = await client.functions.invoke('fetch-emails', {
    'body': {'user_id': user_id}
})
```

**Schedule with pg_cron:**
```sql
SELECT cron.schedule(
    'fetch-emails',
    '*/5 * * * *',
    $$
    SELECT supabase.functions.invoke('fetch-emails');
    $$
);
```

**Pros:**
- ✅ Serverless (no worker process to manage)
- ✅ Scales to zero (only pay for execution)
- ✅ Built into Supabase (no new service)
- ✅ Automatic retries

**Cons:**
- ⚠️ Deno/TypeScript (not Python)
- ⚠️ 60s timeout limit (long tasks need chunking)
- ⚠️ Less control than FastAPI worker

**Cost:** Supabase free tier: 500k function invocations/month (plenty!)

---

### Option 4: Just Use Cron (Simplest for Polling)

**Stack:**
```
FastAPI + Cron/pg_cron + Supabase
```

**What:** If you just need periodic polling (e.g., fetch emails every 5 min), use cron

**Option 4a: Fly.io Machines with systemd timer**
```ini
# /etc/systemd/system/fetch-emails.timer
[Unit]
Description=Fetch emails every 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

**Option 4b: pg_cron (built into Supabase)**
```sql
-- Call your API endpoint every 5 minutes
SELECT cron.schedule(
    'fetch-emails',
    '*/5 * * * *',
    $$
    SELECT net.http_post(
        url := 'https://selko-api.fly.dev/internal/fetch-emails',
        headers := '{"Authorization": "Bearer SECRET"}'::jsonb
    );
    $$
);
```

**Option 4c: GitHub Actions (free cron)**
```yaml
# .github/workflows/cron.yml
name: Fetch Emails
on:
  schedule:
    - cron: '*/5 * * * *'  # Every 5 minutes

jobs:
  fetch:
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -X POST https://selko-api.fly.dev/internal/fetch-emails \
            -H "Authorization: Bearer ${{ secrets.CRON_SECRET }}"
```

**Pros:**
- ✅ Extremely simple
- ✅ No worker process needed
- ✅ No queue infrastructure

**Cons:**
- ⚠️ Only works for periodic tasks (not event-driven)
- ⚠️ No retry logic (handle in endpoint)

**Cost:** $0 (all options are free)

---

## Recommendation: Start with Option 1

### Phase 1: POC (Now) - Bare Minimum ⭐

**Use:**
- FastAPI (APIs)
- FastAPI BackgroundTasks (simple async jobs)
- pg_cron or systemd timer (polling)
- Supabase (database + storage)

**Why:**
- Zero new infrastructure
- You already have everything
- Simplest to develop and deploy
- Free

**Example:**
```python
from fastapi import FastAPI, BackgroundTasks

app = FastAPI()

@app.post("/emails/fetch")
async def fetch_emails(background_tasks: BackgroundTasks):
    # Trigger async job (runs in-process, doesn't block response)
    background_tasks.add_task(fetch_and_store_emails)
    return {"status": "started"}

async def fetch_and_store_emails():
    # Your existing CLI logic
    # Runs async, doesn't block the API
    client = get_authenticated_client()
    messages = fetch_gmail_messages()
    save_emails(client, messages)
```

**Deploy:**
```bash
fly deploy  # That's it!
```

---

### Phase 2: MVP - Add Queue Only If Needed

**When you hit these limits:**
- Tasks take >30 seconds (blocking)
- Need guaranteed execution (retries)
- Tasks fail and you're losing data

**Then add:**
- PostgreSQL table-based queue (Option 2a) - Free, simple
- OR Redis + ARQ if you have complex workflows

**But NOT before you actually need it!**

---

## What About Redis?

### Redis is Great For:
- ✅ Caching (fast key-value lookups)
- ✅ Rate limiting (counters, sliding windows)
- ✅ Session storage
- ✅ Real-time leaderboards, counters
- ✅ High-throughput job queues (1000s/second)

### PostgreSQL is Great For:
- ✅ Persistent data (ACID guarantees)
- ✅ Complex queries (joins, aggregations)
- ✅ Low-to-medium volume queues (<100/sec)
- ✅ Transactional workflows

### For Your Use Case (POC/MVP):
- **Caching?** Don't need it yet (premature optimization)
- **Rate limiting?** Can use PostgreSQL or in-memory dict
- **Sessions?** Supabase handles auth
- **Job queue?** PostgreSQL table is fine for low volume

**Verdict:** You don't need Redis now. Maybe later at scale.

---

## Updated Recommendations

### Absolute Minimum (POC) ⭐⭐⭐
```
FastAPI + Supabase
```
- **Cost:** $0/mo
- **Complexity:** Minimal
- **When to use:** Right now (POC phase)

### Add When You Have Real Background Jobs (MVP)
```
FastAPI + PostgreSQL Queue + Supabase
```
- **Cost:** $0/mo (uses existing Supabase)
- **Complexity:** Low (simple table + polling)
- **When to use:** When BackgroundTasks isn't enough

### Add When You're Actually Scaling (Growth)
```
FastAPI + Redis + ARQ + Supabase
```
- **Cost:** ~$10-20/mo (Upstash Redis)
- **Complexity:** Medium
- **When to use:** 1000s of jobs/hour, distributed workers

---

## Decision Tree

```
Do you need background jobs?
├─ No → Just FastAPI + Supabase (POC)
│
└─ Yes
   ├─ Simple async tasks (<10s)?
   │  └─ FastAPI BackgroundTasks ✅
   │
   └─ Longer tasks or need retries?
      ├─ <100 jobs/hour?
      │  └─ PostgreSQL table queue ✅
      │
      └─ >1000 jobs/hour?
         └─ Redis + ARQ

Do you need polling?
├─ Every N minutes (simple)?
│  └─ pg_cron or systemd timer ✅
│
└─ Complex scheduling?
   └─ APScheduler (still no Redis!)
```

---

## Cost Comparison

| Stack | POC Cost | MVP Cost | Complexity |
|-------|----------|----------|------------|
| **FastAPI + Supabase** ⭐ | **$0** | **$25** | **Low** |
| FastAPI + PG Queue + Supabase | $0 | $25 | Medium |
| FastAPI + Edge Functions + Supabase | $0 | $25 | Medium |
| FastAPI + Redis + ARQ + Supabase | $0-10 | $35-45 | High |

**All can run on Fly.io free tier for POC.**

---

## My Updated Recommendation

### For POC (Now):
1. ✅ Deploy FastAPI to Fly.io (free tier)
2. ✅ Use FastAPI `BackgroundTasks` for async jobs
3. ✅ Use pg_cron (Supabase) for polling Gmail every 5 min
4. ✅ No Redis, no ARQ, no extra services

### For MVP (Later):
1. If BackgroundTasks isn't enough → Add PostgreSQL queue (still free!)
2. If you actually need caching → Add Redis (when you measure the need)

### For Scale (Much Later):
1. When PostgreSQL queue can't keep up → Migrate to Redis + ARQ
2. When single instance isn't enough → Horizontal scaling

---

## Bottom Line

**You asked:** "Why do we need Redis?"

**Answer:** **You don't.** Not for POC, probably not for MVP.

**You asked:** "Can't we just use Supabase database for queues?"

**Answer:** **Yes!** PostgreSQL can absolutely handle queues for low-medium volume.

**You asked:** "Any other way to simplify?"

**Answer:** **Start with just FastAPI + Supabase.** Add complexity only when you hit real limits.

---

## Next Steps

**I recommend:**
1. Forget about Redis/ARQ for now
2. Use FastAPI + Supabase (2 components, not 6)
3. Use BackgroundTasks for simple async work
4. Use pg_cron for polling
5. Add PostgreSQL queue if you need retries
6. Add Redis only when you actually measure the need

**Want me to:**
- Update the evaluations to reflect this simpler approach?
- Create a minimal deployment guide (FastAPI + Supabase only)?
- Help you set up pg_cron for email polling?

**You were right to push back.** Simpler is better, especially for POC.
