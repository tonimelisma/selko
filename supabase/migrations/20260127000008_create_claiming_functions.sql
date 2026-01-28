-- Migration: Create atomic claiming RPC functions for status-based workers
-- Uses FOR UPDATE SKIP LOCKED for safe concurrent claiming

-- Claim the next unprocessed email for a worker
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

COMMENT ON FUNCTION claim_unprocessed_email IS 'Atomically claim next pending email for LLM processing';


-- Claim the next approved event for calendar sync
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

COMMENT ON FUNCTION claim_approved_event IS 'Atomically claim next approved event for calendar sync';


-- Unlock expired email locks (for recovery from crashed workers)
CREATE OR REPLACE FUNCTION unlock_expired_email_locks()
RETURNS integer AS $$
DECLARE
    v_count integer;
BEGIN
    UPDATE emails
    SET processing_status = 'pending',
        locked_by = NULL,
        locked_until = NULL
    WHERE processing_status = 'processing'
      AND locked_until < now();

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION unlock_expired_email_locks IS 'Reset expired email locks back to pending for retry';


-- Unlock expired event locks (for recovery from crashed workers)
CREATE OR REPLACE FUNCTION unlock_expired_event_locks()
RETURNS integer AS $$
DECLARE
    v_count integer;
BEGIN
    UPDATE events
    SET status = 'approved',
        locked_by = NULL,
        locked_until = NULL
    WHERE status = 'syncing'
      AND locked_until < now();

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION unlock_expired_event_locks IS 'Reset expired event locks back to approved for retry';
