-- C3: wire automatic cancellation into the durable worker state machine.
-- The earlier cancellation migration supplied columns and a claim stub; this
-- migration makes the transition, recovery, and retry invariants executable.

ALTER TABLE public.emails DROP CONSTRAINT IF EXISTS emails_processing_outcome_check;
ALTER TABLE public.emails ADD CONSTRAINT emails_processing_outcome_check
    CHECK (processing_outcome IS NULL OR processing_outcome IN (
        'no_event', 'event_matched', 'event_created', 'event_updated',
        'event_created_and_updated', 'event_cancelled', 'calendar_invite',
        'cancellation_unmatched', 'cancellation_ambiguous'
    ));

CREATE OR REPLACE FUNCTION public.enforce_event_cancellation_transition()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    IF NEW.status = 'cancel_queued' THEN
        NEW.calendar_sync_action := 'cancel';
        IF OLD.status IS DISTINCT FROM 'cancel_queued' THEN
            NEW.calendar_work_generation := OLD.calendar_work_generation + 1;
            NEW.sync_attempts := 0;
            NEW.next_retry_at := NULL;
            NEW.dead_letter_reason := NULL;
            NEW.dead_letter_at := NULL;
            NEW.sync_error := NULL;
            NEW.sync_failure_code := NULL;
        END IF;
    ELSIF NEW.status = 'cancelled' THEN
        NEW.calendar_sync_action := 'cancel';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_enforce_event_cancellation_transition ON public.events;
CREATE TRIGGER trg_enforce_event_cancellation_transition
    BEFORE UPDATE ON public.events
    FOR EACH ROW
    EXECUTE FUNCTION public.enforce_event_cancellation_transition();

-- A crashed cancellation worker returns to the cancellation queue, never to
-- approved/upsert. The next claim receives a fresh generation.
CREATE OR REPLACE FUNCTION public.unlock_expired_event_locks()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_count integer;
BEGIN
    UPDATE public.events
    SET status = CASE WHEN calendar_sync_action = 'cancel' THEN 'cancel_queued' ELSE 'approved' END,
        locked_by = NULL,
        locked_until = NULL
    WHERE status = 'syncing' AND locked_until < now();
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;

-- OAuth recovery must discover both normal upserts and queued cancellations.
CREATE OR REPLACE FUNCTION public.requeue_calendar_recovery_batch(
    p_recovery_id uuid,
    p_worker_id text,
    p_batch_size integer DEFAULT 100,
    p_max_batches integer DEFAULT 5
) RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
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
    IF v_user_id IS NULL THEN RETURN -1; END IF;

    LOOP
        WITH batch AS (
            SELECT id FROM public.events
            WHERE user_id = v_user_id
              AND status IN ('approved', 'cancel_queued')
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
        UPDATE public.integration_recoveries
        SET status = 'pending', locked_by = NULL, locked_until = NULL, updated_at = now()
        WHERE id = p_recovery_id;
        RETURN v_total_tagged;
    END IF;

    SELECT
        count(*) FILTER (WHERE status IN ('synced', 'cancelled')),
        count(*) FILTER (WHERE status IN ('approved', 'syncing', 'cancel_queued')),
        count(*) FILTER (WHERE status = 'sync_failed')
    INTO v_completed, v_remaining, v_errored
    FROM public.events WHERE recovery_id = p_recovery_id;

    IF v_remaining = 0 THEN
        UPDATE public.integration_recoveries SET
            status = CASE WHEN v_errored > 0 THEN 'completed_with_errors' ELSE 'completed' END,
            completed_count = v_completed, remaining_count = 0,
            locked_by = NULL, locked_until = NULL, completed_at = now(), updated_at = now()
        WHERE id = p_recovery_id;
    ELSE
        UPDATE public.integration_recoveries SET
            status = 'waiting', completed_count = v_completed,
            remaining_count = v_remaining, locked_by = NULL, locked_until = NULL,
            updated_at = now()
        WHERE id = p_recovery_id;
    END IF;
    RETURN v_total_tagged;
END;
$$;

CREATE OR REPLACE FUNCTION public.refresh_waiting_calendar_recoveries(
    p_batch_size integer DEFAULT 20
) RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
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
            count(*) FILTER (WHERE status IN ('synced', 'cancelled')),
            count(*) FILTER (WHERE status IN ('approved', 'syncing', 'cancel_queued')),
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
END;
$$;

REVOKE ALL ON FUNCTION public.unlock_expired_event_locks() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.unlock_expired_event_locks() TO service_role;
REVOKE ALL ON FUNCTION public.requeue_calendar_recovery_batch(uuid, text, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.requeue_calendar_recovery_batch(uuid, text, integer, integer) TO service_role;
REVOKE ALL ON FUNCTION public.refresh_waiting_calendar_recoveries(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.refresh_waiting_calendar_recoveries(integer) TO service_role;

-- All application callers now use claim_calendar_work. Leaving the legacy
-- alias callable would make it too easy to reintroduce an upsert-only path.
DROP FUNCTION IF EXISTS public.claim_approved_event(text, integer);
