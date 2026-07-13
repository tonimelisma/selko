-- Migration: Claim unprocessed emails oldest-first
--
-- Bulk scans ingest newest-first, so a bulk backlog processed in insertion
-- order let older emails "update" events already created from newer emails
-- of the same thread (out-of-order processing). Claim by date_sent instead
-- of created_at so emails are always processed in the order they were sent.

CREATE OR REPLACE FUNCTION public.claim_unprocessed_email(
    p_worker_id text,
    p_lock_duration_seconds integer DEFAULT 300
)
RETURNS SETOF public.emails
LANGUAGE plpgsql
AS $$
DECLARE
    v_email public.emails;
BEGIN
    SELECT * INTO v_email
    FROM public.emails
    WHERE processing_status = 'pending'
      AND attempts < max_attempts
      AND (locked_until IS NULL OR locked_until < now())
      AND (next_retry_at IS NULL OR next_retry_at <= now())
    ORDER BY date_sent ASC NULLS LAST, created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF v_email.id IS NOT NULL THEN
        UPDATE public.emails
        SET processing_status = 'processing',
            processing_error = NULL,
            locked_by = p_worker_id,
            locked_until = now() + (p_lock_duration_seconds || ' seconds')::interval,
            attempts = attempts + 1
        WHERE id = v_email.id
        RETURNING * INTO v_email;
        RETURN NEXT v_email;
    END IF;
END;
$$;

COMMENT ON FUNCTION public.claim_unprocessed_email IS 'Atomically claim next pending email for LLM processing, oldest date_sent first (respects next_retry_at)';
