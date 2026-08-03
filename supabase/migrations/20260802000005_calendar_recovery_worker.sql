-- Calendar recovery worker stage (oauth-reconnect-catch-up.md, section 3 —
-- Google Calendar only; email needs no recovery worker, see 20260802000004).
--
-- Design note: because the earlier structured-classification increment
-- (20260802000003) already parks OAuth-blocked events at status='approved'
-- with sync_attempts preserved (never dead-lettered), the actual retry is
-- already free: the moment complete_integration_reauthorization makes the
-- integration active again, claim_approved_event's active-integration check
-- passes and the normal worker drains the event on its next poll. Nothing
-- here re-attempts a sync or talks to Google Calendar.
--
-- These RPCs exist purely to (a) tag which events belong to a recovery
-- generation, and (b) track completion counts, so the UI can show
-- "Catching up — N remaining" instead of just "Connected". Both are pure SQL
-- with no external I/O, so completion tracking (`refresh_waiting_calendar_
-- recoveries`) needs no external claim/lock step of its own — a single
-- FOR UPDATE SKIP LOCKED pass per call is enough.

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
BEGIN
    SELECT user_id INTO v_user_id
    FROM public.integration_recoveries
    WHERE id = p_recovery_id AND locked_by = p_worker_id AND locked_until > now();

    IF v_user_id IS NULL THEN
        RETURN -1; -- claim expired or held by another worker
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
        -- Hit the per-call ceiling with more still to tag: release so the
        -- next claim continues where this left off.
        UPDATE public.integration_recoveries SET
            status = 'pending', locked_by = NULL, locked_until = NULL, updated_at = now()
        WHERE id = p_recovery_id;
        RETURN v_total_tagged;
    END IF;

    SELECT
        count(*) FILTER (WHERE status = 'synced'),
        count(*) FILTER (WHERE status IN ('approved', 'syncing')),
        count(*) FILTER (WHERE status = 'sync_failed')
    INTO v_completed, v_remaining, v_errored
    FROM public.events WHERE recovery_id = p_recovery_id;

    IF v_remaining = 0 THEN
        UPDATE public.integration_recoveries SET
            status = CASE WHEN v_errored > 0 THEN 'completed_with_errors' ELSE 'completed' END,
            completed_count = v_completed, remaining_count = 0,
            locked_by = NULL, locked_until = NULL,
            completed_at = now(), updated_at = now()
        WHERE id = p_recovery_id;
    ELSE
        UPDATE public.integration_recoveries SET
            status = 'waiting',
            completed_count = v_completed, remaining_count = v_remaining,
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
    v_processed integer := 0;
BEGIN
    FOR v_recovery_id IN
        SELECT id FROM public.integration_recoveries
        WHERE status = 'waiting'
        ORDER BY updated_at
        LIMIT p_batch_size
        FOR UPDATE SKIP LOCKED
    LOOP
        SELECT
            count(*) FILTER (WHERE status = 'synced'),
            count(*) FILTER (WHERE status IN ('approved', 'syncing')),
            count(*) FILTER (WHERE status = 'sync_failed')
        INTO v_completed, v_remaining, v_errored
        FROM public.events WHERE recovery_id = v_recovery_id;

        IF v_remaining = 0 THEN
            UPDATE public.integration_recoveries SET
                status = CASE WHEN v_errored > 0 THEN 'completed_with_errors' ELSE 'completed' END,
                completed_count = v_completed, remaining_count = 0,
                completed_at = now(), updated_at = now()
            WHERE id = v_recovery_id;
        ELSE
            UPDATE public.integration_recoveries SET
                completed_count = v_completed, remaining_count = v_remaining, updated_at = now()
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

COMMENT ON FUNCTION public.requeue_calendar_recovery_batch IS
    'Service-role-only: tags a claimed recovery''s OAuth-blocked approved events with recovery_id and advances its status; the events themselves resync through the normal approved-event queue';
COMMENT ON FUNCTION public.refresh_waiting_calendar_recoveries IS
    'Service-role-only: recomputes progress for waiting recoveries and finalizes ones whose tagged events have all reached a terminal state';
