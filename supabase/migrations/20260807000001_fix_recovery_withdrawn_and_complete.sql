-- Hardening inc 7a: incomplete status vocabulary
-- refresh_waiting_calendar_recoveries counted synced/approved,syncing/sync_failed
-- but missed cancelled/rejected. A tagged event the user rejects mid-recovery
-- counted as none, so remaining dropped and recovery finalized with undercounted
-- completed_count — UI renders "Caught up — 3 of 5". Fix: count withdrawn
-- explicitly (7a) so discovered = completed + remaining + errored + withdrawn
-- closes.
--
-- Either folding into completed_count or adding withdrawn_count is allowed;
-- withdrawn_count is chosen so the UI arithmetic is auditable and the fix is
-- reversible. Existing rows default to 0 (no withdrawn yet).

ALTER TABLE public.integration_recoveries
    ADD COLUMN IF NOT EXISTS withdrawn_count integer NOT NULL DEFAULT 0;

-- Update requeue to count withdrawn events and persist withdrawn_count
CREATE OR REPLACE FUNCTION public.requeue_calendar_recovery_batch(
    p_recovery_id uuid,
    p_worker_id text,
    p_batch_size integer DEFAULT 100,
    p_max_batches integer DEFAULT 5
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_user_id uuid;
    v_tagged integer;
    v_total_tagged integer := 0;
    v_batches integer := 0;
    v_completed integer;
    v_remaining integer;
    v_errored integer;
    v_withdrawn integer;
BEGIN
    SELECT user_id INTO v_user_id
    FROM public.integration_recoveries
    WHERE id = p_recovery_id AND locked_by = p_worker_id AND locked_until > now();

    IF v_user_id IS NULL THEN
        RETURN -1;
    END IF;

    LOOP
        WITH batch AS (
            SELECT id FROM public.events
            WHERE user_id = v_user_id
              AND status = 'approved'
              AND sync_failure_code IN ('oauth_required', 'oauth_scope_required')
              AND recovery_id IS NULL
            ORDER BY updated_at
            LIMIT p_batch_size
            FOR UPDATE SKIP LOCKED
        )
        UPDATE public.events SET recovery_id = p_recovery_id
        WHERE id IN (SELECT id FROM batch);
        GET DIAGNOSTICS v_tagged = ROW_COUNT;

        v_total_tagged := v_total_tagged + v_tagged;
        v_batches := v_batches + 1;

        EXIT WHEN v_tagged < p_batch_size OR v_batches >= p_max_batches;
    END LOOP;

    UPDATE public.integration_recoveries SET
        discovered_count = discovered_count + v_total_tagged,
        requeued_count = requeued_count + v_total_tagged,
        updated_at = now()
    WHERE id = p_recovery_id;

    IF v_tagged >= p_batch_size THEN
        UPDATE public.integration_recoveries SET
            status = 'pending', locked_by = NULL, locked_until = NULL, updated_at = now()
        WHERE id = p_recovery_id;
        RETURN v_total_tagged;
    END IF;

    -- 7a: include cancelled/rejected as withdrawn so finalization is not undercounted
    SELECT
        count(*) FILTER (WHERE status = 'synced'),
        count(*) FILTER (WHERE status IN ('approved', 'syncing')),
        count(*) FILTER (WHERE status = 'sync_failed'),
        count(*) FILTER (WHERE status IN ('cancelled', 'rejected'))
    INTO v_completed, v_remaining, v_errored, v_withdrawn
    FROM public.events WHERE recovery_id = p_recovery_id;

    IF v_remaining = 0 THEN
        UPDATE public.integration_recoveries SET
            status = CASE WHEN v_errored > 0 THEN 'completed_with_errors' ELSE 'completed' END,
            completed_count = v_completed, remaining_count = 0,
            withdrawn_count = v_withdrawn,
            locked_by = NULL, locked_until = NULL,
            completed_at = now(), updated_at = now()
        WHERE id = p_recovery_id;
    ELSE
        UPDATE public.integration_recoveries SET
            status = 'waiting',
            completed_count = v_completed, remaining_count = v_remaining,
            withdrawn_count = v_withdrawn,
            locked_by = NULL, locked_until = NULL, updated_at = now()
        WHERE id = p_recovery_id;
    END IF;

    RETURN v_total_tagged;
END; $$;

CREATE OR REPLACE FUNCTION public.refresh_waiting_calendar_recoveries(
    p_batch_size integer DEFAULT 20
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_recovery_id uuid;
    v_completed integer;
    v_remaining integer;
    v_errored integer;
    v_withdrawn integer;
    v_processed integer := 0;
BEGIN
    FOR v_recovery_id IN
        SELECT id FROM public.integration_recoveries
        WHERE status = 'waiting'
        ORDER BY updated_at
        LIMIT p_batch_size
        FOR UPDATE SKIP LOCKED
    LOOP
        -- 7a: include cancelled/rejected as withdrawn
        SELECT
            count(*) FILTER (WHERE status = 'synced'),
            count(*) FILTER (WHERE status IN ('approved', 'syncing')),
            count(*) FILTER (WHERE status = 'sync_failed'),
            count(*) FILTER (WHERE status IN ('cancelled', 'rejected'))
        INTO v_completed, v_remaining, v_errored, v_withdrawn
        FROM public.events WHERE recovery_id = v_recovery_id;

        IF v_remaining = 0 THEN
            UPDATE public.integration_recoveries SET
                status = CASE WHEN v_errored > 0 THEN 'completed_with_errors' ELSE 'completed' END,
                completed_count = v_completed, remaining_count = 0,
                withdrawn_count = v_withdrawn,
                completed_at = now(), updated_at = now()
            WHERE id = v_recovery_id;
        ELSE
            UPDATE public.integration_recoveries SET
                completed_count = v_completed, remaining_count = v_remaining,
                withdrawn_count = v_withdrawn, updated_at = now()
            WHERE id = v_recovery_id;
        END IF;

        v_processed := v_processed + 1;
    END LOOP;

    RETURN v_processed;
END; $$;

REVOKE ALL ON FUNCTION public.requeue_calendar_recovery_batch(uuid, text, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.requeue_calendar_recovery_batch(uuid, text, integer, integer) TO service_role;

REVOKE ALL ON FUNCTION public.refresh_waiting_calendar_recoveries(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.refresh_waiting_calendar_recoveries(integer) TO service_role;

COMMENT ON COLUMN public.integration_recoveries.withdrawn_count IS
    '7a: events tagged to this recovery that were cancelled/rejected mid-catch-up (terminal-not-errored). withdrawn + completed + errored closes against discovered.';
