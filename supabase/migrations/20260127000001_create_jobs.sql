-- Create jobs table for async job queue
-- Part of the Async Monolith pattern using PostgreSQL as the queue backend

CREATE TABLE public.jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    
    -- Job type and payload
    job_type text NOT NULL CHECK (job_type IN (
        'email_fetch',      -- Fetch new emails from Gmail
        'email_process',    -- Process email through LLM
        'calendar_sync'     -- Write approved events to calendar
    )),
    payload jsonb NOT NULL DEFAULT '{}',
    
    -- Status tracking
    status text NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending',      -- Waiting to be processed
        'processing',   -- Currently being worked on
        'completed',    -- Successfully finished
        'failed',       -- Failed (may retry)
        'dead'          -- Failed after max retries
    )),
    
    -- Priority and ordering
    priority integer NOT NULL DEFAULT 0,  -- Higher = more urgent
    scheduled_at timestamptz NOT NULL DEFAULT now(),
    
    -- Retry logic
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 3,
    last_error text,
    
    -- Timing
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    completed_at timestamptz,
    
    -- Prevent duplicate work
    locked_until timestamptz,
    locked_by text
);

-- Indexes for efficient queue operations
-- Partial index on pending jobs for fast claiming
CREATE INDEX idx_jobs_pending ON public.jobs(status, priority DESC, scheduled_at)
    WHERE status = 'pending';

-- Index for querying user's jobs
CREATE INDEX idx_jobs_user ON public.jobs(user_id);

-- Index for filtering by job type
CREATE INDEX idx_jobs_type ON public.jobs(job_type);

-- Index for cleanup queries (finding old completed/failed jobs)
CREATE INDEX idx_jobs_cleanup ON public.jobs(status, completed_at)
    WHERE status IN ('completed', 'failed', 'dead');

-- Row Level Security
ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;

-- Users can view their own jobs
CREATE POLICY "Users can view own jobs" ON public.jobs
    FOR SELECT USING (auth.uid() = user_id);

-- Service role can do everything (for worker processes)
CREATE POLICY "Service role full access" ON public.jobs
    FOR ALL USING (true);

COMMENT ON TABLE public.jobs IS 'Job queue for async background processing using PostgreSQL';
COMMENT ON COLUMN public.jobs.job_type IS 'Type of job: email_fetch, email_process, calendar_sync';
COMMENT ON COLUMN public.jobs.payload IS 'JSON payload specific to job type';
COMMENT ON COLUMN public.jobs.status IS 'Job status: pending -> processing -> completed/failed/dead';
COMMENT ON COLUMN public.jobs.priority IS 'Higher number = higher priority (0 is default)';
COMMENT ON COLUMN public.jobs.locked_until IS 'Prevents other workers from claiming until this time';
COMMENT ON COLUMN public.jobs.locked_by IS 'Worker ID that claimed this job';
