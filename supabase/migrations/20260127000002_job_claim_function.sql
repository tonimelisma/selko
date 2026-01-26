-- Atomic job claiming function using FOR UPDATE SKIP LOCKED
-- This ensures multiple workers can safely claim jobs without conflicts

CREATE OR REPLACE FUNCTION claim_next_job(
    p_job_types text[],
    p_worker_id text,
    p_lock_duration_seconds integer DEFAULT 300
) RETURNS SETOF jobs AS $$
DECLARE
    v_job jobs;
BEGIN
    -- Atomically find and claim the next pending job
    -- FOR UPDATE SKIP LOCKED ensures no conflicts between workers
    SELECT * INTO v_job
    FROM jobs
    WHERE status = 'pending'
      AND job_type = ANY(p_job_types)
      AND scheduled_at <= now()
      AND (locked_until IS NULL OR locked_until < now())
    ORDER BY priority DESC, scheduled_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;
    
    -- If we found a job, update it atomically
    IF v_job.id IS NOT NULL THEN
        UPDATE jobs SET
            status = 'processing',
            locked_by = p_worker_id,
            locked_until = now() + (p_lock_duration_seconds || ' seconds')::interval,
            started_at = now(),
            attempts = attempts + 1
        WHERE id = v_job.id
        RETURNING * INTO v_job;
        
        RETURN NEXT v_job;
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION claim_next_job IS 'Atomically claim next pending job for processing';

-- Function to unlock stuck jobs (jobs that exceeded their lock duration)
CREATE OR REPLACE FUNCTION unlock_expired_jobs()
RETURNS integer AS $$
DECLARE
    v_count integer;
BEGIN
    UPDATE jobs
    SET status = 'pending',
        locked_by = NULL,
        locked_until = NULL
    WHERE status = 'processing'
      AND locked_until < now();
    
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION unlock_expired_jobs IS 'Reset expired job locks back to pending';
