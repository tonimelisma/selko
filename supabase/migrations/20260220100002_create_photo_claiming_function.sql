-- Claiming RPC for photo processing worker

CREATE OR REPLACE FUNCTION public.claim_pending_photo(
    p_worker_id TEXT,
    p_lock_duration_seconds INTEGER DEFAULT 300
)
RETURNS SETOF public.photos
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_photo public.photos;
BEGIN
    SELECT * INTO v_photo
    FROM public.photos
    WHERE processing_status = 'pending'
      AND attempts < max_attempts
      AND (locked_until IS NULL OR locked_until < now())
      AND (next_retry_at IS NULL OR next_retry_at <= now())
    ORDER BY created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF v_photo.id IS NOT NULL THEN
        UPDATE public.photos SET
            processing_status = 'processing',
            locked_by = p_worker_id,
            locked_until = now() + (p_lock_duration_seconds || ' seconds')::interval,
            attempts = attempts + 1
        WHERE id = v_photo.id
        RETURNING * INTO v_photo;

        RETURN NEXT v_photo;
    END IF;
END;
$$;

-- Unlock function for expired photo locks
CREATE OR REPLACE FUNCTION public.unlock_expired_photo_locks()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    WITH unlocked AS (
        UPDATE public.photos SET
            processing_status = 'pending',
            locked_by = NULL,
            locked_until = NULL
        WHERE processing_status = 'processing'
          AND locked_until < now()
        RETURNING id
    )
    SELECT count(*) INTO v_count FROM unlocked;
    RETURN v_count;
END;
$$;
