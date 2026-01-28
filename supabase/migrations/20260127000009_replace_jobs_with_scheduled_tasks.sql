-- Migration: Replace jobs table with scheduled_tasks table
-- The jobs table is no longer needed - email_process and calendar_sync work directly from data tables
-- scheduled_tasks is only for periodic tasks like email_fetch

-- Drop old job-related functions
DROP FUNCTION IF EXISTS claim_next_job(text[], text, integer);
DROP FUNCTION IF EXISTS unlock_expired_jobs();

-- Drop the jobs table
DROP TABLE IF EXISTS public.jobs;

-- Create scheduled_tasks table for periodic tasks only
-- Currently only email_fetch needs this (triggered by cron/scheduler)
CREATE TABLE public.scheduled_tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,

    -- Task type (only periodic/scheduled tasks go here)
    task_type text NOT NULL CHECK (task_type IN (
        'email_fetch'      -- Fetch new emails from Gmail (triggered every 5 min)
    )),
    payload jsonb NOT NULL DEFAULT '{}',

    -- Status tracking
    status text NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending',      -- Waiting to be processed
        'processing',   -- Currently being worked on
        'completed',    -- Successfully finished
        'failed'        -- Failed (will not retry for scheduled tasks)
    )),

    -- Scheduling
    scheduled_at timestamptz NOT NULL DEFAULT now(),

    -- Locking for concurrent workers
    locked_until timestamptz,
    locked_by text,

    -- Timing
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    completed_at timestamptz,

    -- Error tracking
    last_error text
);

-- Indexes for efficient task claiming
CREATE INDEX idx_scheduled_tasks_pending ON public.scheduled_tasks(status, scheduled_at)
    WHERE status = 'pending';

CREATE INDEX idx_scheduled_tasks_user ON public.scheduled_tasks(user_id);

-- Row Level Security
ALTER TABLE public.scheduled_tasks ENABLE ROW LEVEL SECURITY;

-- Users can view their own tasks
CREATE POLICY "Users can view own scheduled tasks" ON public.scheduled_tasks
    FOR SELECT USING (auth.uid() = user_id);

-- Service role can do everything (for worker processes)
CREATE POLICY "Service role full access to scheduled tasks" ON public.scheduled_tasks
    FOR ALL USING (true);

COMMENT ON TABLE public.scheduled_tasks IS 'Scheduled/periodic tasks (email_fetch). Data processing uses status-based claiming directly from data tables.';
COMMENT ON COLUMN public.scheduled_tasks.task_type IS 'Type of scheduled task (currently only email_fetch)';
COMMENT ON COLUMN public.scheduled_tasks.status IS 'Task status: pending -> processing -> completed/failed';


-- Atomic claiming function for scheduled tasks
CREATE OR REPLACE FUNCTION claim_next_scheduled_task(
    p_task_types text[],
    p_worker_id text,
    p_lock_duration_seconds integer DEFAULT 300
) RETURNS SETOF scheduled_tasks AS $$
DECLARE
    v_task scheduled_tasks;
BEGIN
    -- Atomically find and claim the next pending task
    SELECT * INTO v_task
    FROM scheduled_tasks
    WHERE status = 'pending'
      AND task_type = ANY(p_task_types)
      AND scheduled_at <= now()
      AND (locked_until IS NULL OR locked_until < now())
    ORDER BY scheduled_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    -- If we found a task, update it atomically
    IF v_task.id IS NOT NULL THEN
        UPDATE scheduled_tasks SET
            status = 'processing',
            locked_by = p_worker_id,
            locked_until = now() + (p_lock_duration_seconds || ' seconds')::interval,
            started_at = now()
        WHERE id = v_task.id
        RETURNING * INTO v_task;

        RETURN NEXT v_task;
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION claim_next_scheduled_task IS 'Atomically claim next pending scheduled task for processing';


-- Function to unlock stuck scheduled tasks
CREATE OR REPLACE FUNCTION unlock_expired_scheduled_tasks()
RETURNS integer AS $$
DECLARE
    v_count integer;
BEGIN
    UPDATE scheduled_tasks
    SET status = 'pending',
        locked_by = NULL,
        locked_until = NULL
    WHERE status = 'processing'
      AND locked_until < now();

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION unlock_expired_scheduled_tasks IS 'Reset expired scheduled task locks back to pending';
