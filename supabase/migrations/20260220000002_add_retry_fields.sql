-- Migration: Add retry and dead-letter fields for reliability
-- Adds next_retry_at for exponential backoff, dead_letter columns for failed items

-- Email retry and dead-letter fields
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS dead_letter_reason TEXT;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS dead_letter_at TIMESTAMPTZ;

-- Event retry and dead-letter fields
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS dead_letter_reason TEXT;
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS dead_letter_at TIMESTAMPTZ;
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;

-- Update claim_unprocessed_email to respect next_retry_at
CREATE OR REPLACE FUNCTION claim_unprocessed_email(
    p_worker_id text,
    p_lock_duration_seconds integer DEFAULT 300
) RETURNS SETOF emails AS $$
DECLARE
    v_email emails;
BEGIN
    -- Atomically find and claim the next pending email
    -- FOR UPDATE SKIP LOCKED ensures no conflicts between workers
    SELECT * INTO v_email
    FROM emails
    WHERE processing_status = 'pending'
      AND attempts < max_attempts
      AND (locked_until IS NULL OR locked_until < now())
      AND (next_retry_at IS NULL OR next_retry_at <= now())
    ORDER BY created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    -- If we found an email, update it atomically
    IF v_email.id IS NOT NULL THEN
        UPDATE emails SET
            processing_status = 'processing',
            locked_by = p_worker_id,
            locked_until = now() + (p_lock_duration_seconds || ' seconds')::interval,
            attempts = attempts + 1
        WHERE id = v_email.id
        RETURNING * INTO v_email;

        RETURN NEXT v_email;
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION claim_unprocessed_email IS 'Atomically claim next pending email for LLM processing (respects next_retry_at)';

-- Update claim_approved_event to respect next_retry_at
CREATE OR REPLACE FUNCTION claim_approved_event(
    p_worker_id text,
    p_lock_duration_seconds integer DEFAULT 300
) RETURNS SETOF events AS $$
DECLARE
    v_event events;
BEGIN
    -- Atomically find and claim the next approved event
    -- FOR UPDATE SKIP LOCKED ensures no conflicts between workers
    SELECT * INTO v_event
    FROM events
    WHERE status = 'approved'
      AND sync_attempts < max_sync_attempts
      AND (locked_until IS NULL OR locked_until < now())
      AND (next_retry_at IS NULL OR next_retry_at <= now())
    ORDER BY updated_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    -- If we found an event, update it atomically
    IF v_event.id IS NOT NULL THEN
        UPDATE events SET
            status = 'syncing',
            locked_by = p_worker_id,
            locked_until = now() + (p_lock_duration_seconds || ' seconds')::interval,
            sync_attempts = sync_attempts + 1
        WHERE id = v_event.id
        RETURNING * INTO v_event;

        RETURN NEXT v_event;
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION claim_approved_event IS 'Atomically claim next approved event for calendar sync (respects next_retry_at)';
