-- The durable email claim functions return a column named integration_id.
-- In PL/pgSQL that OUT parameter is also a variable, so the unqualified
-- integration_id in the email_sync_runs UPDATE is ambiguous at first call.
-- Keep the already-published function signature and qualify the table column.

CREATE OR REPLACE FUNCTION public.claim_due_email_sync(p_worker_id text, p_lease_seconds integer)
RETURNS TABLE (integration_id uuid, user_id uuid, provider text, run_id uuid,
               run_kind text, lease_generation bigint, lease_expires_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_state public.email_sync_state; v_run_id uuid; v_kind text; v_generation bigint;
BEGIN
    SELECT s.* INTO v_state FROM public.email_sync_state s
    JOIN public.integrations i ON i.id = s.integration_id
    WHERE i.status = 'active' AND s.next_poll_at <= now()
      AND (s.lease_expires_at IS NULL OR s.lease_expires_at <= now())
    ORDER BY s.next_poll_at, s.last_success_at NULLS FIRST
    LIMIT 1 FOR UPDATE OF s SKIP LOCKED;
    IF v_state.integration_id IS NULL THEN RETURN; END IF;

    UPDATE public.email_sync_runs r
    SET status = 'abandoned', completed_at = now()
    WHERE r.integration_id = v_state.integration_id AND r.status = 'running';

    v_kind := CASE WHEN v_state.last_success_at IS NULL THEN 'initial' ELSE 'incremental' END;
    v_generation := v_state.lease_generation + 1;
    INSERT INTO public.email_sync_runs (integration_id, user_id, provider, run_kind, status, lease_generation)
    VALUES (v_state.integration_id, v_state.user_id, v_state.provider, v_kind, 'running', v_generation)
    RETURNING id INTO v_run_id;
    UPDATE public.email_sync_state SET lease_owner = p_worker_id,
        lease_generation = v_generation,
        lease_expires_at = now() + make_interval(secs => greatest(p_lease_seconds, 1)),
        last_started_at = now(), updated_at = now()
    WHERE email_sync_state.integration_id = v_state.integration_id;
    RETURN QUERY SELECT v_state.integration_id, v_state.user_id, v_state.provider,
        v_run_id, v_kind, v_generation, now() + make_interval(secs => greatest(p_lease_seconds, 1));
END; $$;

CREATE OR REPLACE FUNCTION public.claim_due_email_reconciliation(p_worker_id text, p_lease_seconds integer)
RETURNS TABLE (integration_id uuid, user_id uuid, provider text, run_id uuid,
               run_kind text, lease_generation bigint, lease_expires_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_state public.email_sync_state; v_run_id uuid; v_kind text; v_generation bigint;
BEGIN
    SELECT s.* INTO v_state FROM public.email_sync_state s
    JOIN public.integrations i ON i.id = s.integration_id
    WHERE i.status = 'active'
      AND (s.lease_expires_at IS NULL OR s.lease_expires_at <= now())
      AND (s.last_reconciled_at IS NULL OR s.last_reconciled_at <= now() - interval '1 day')
      AND s.next_poll_at > now()
    ORDER BY s.last_reconciled_at NULLS FIRST, s.next_poll_at
    LIMIT 1 FOR UPDATE OF s SKIP LOCKED;
    IF v_state.integration_id IS NULL THEN RETURN; END IF;

    UPDATE public.email_sync_runs r
    SET status = 'abandoned', completed_at = now()
    WHERE r.integration_id = v_state.integration_id AND r.status = 'running';

    v_kind := CASE WHEN v_state.last_reconciled_at IS NOT NULL
                        AND v_state.last_reconciled_at <= now() - interval '7 days'
                   THEN 'weekly_reconcile' ELSE 'daily_reconcile' END;
    v_generation := v_state.lease_generation + 1;
    INSERT INTO public.email_sync_runs (integration_id, user_id, provider, run_kind, status, lease_generation)
    VALUES (v_state.integration_id, v_state.user_id, v_state.provider, v_kind, 'running', v_generation)
    RETURNING id INTO v_run_id;
    UPDATE public.email_sync_state SET lease_owner = p_worker_id,
        lease_generation = v_generation,
        lease_expires_at = now() + make_interval(secs => greatest(p_lease_seconds, 1)),
        last_started_at = now(), updated_at = now()
    WHERE email_sync_state.integration_id = v_state.integration_id;
    RETURN QUERY SELECT v_state.integration_id, v_state.user_id, v_state.provider,
        v_run_id, v_kind, v_generation, now() + make_interval(secs => greatest(p_lease_seconds, 1));
END; $$;

REVOKE ALL ON FUNCTION public.claim_due_email_sync(text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_due_email_reconciliation(text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claim_due_email_sync(text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_due_email_reconciliation(text, integer) TO service_role;

-- 20260826000001 dropped and recreated the proposal RPCs after the original
-- grant hardening migration. Re-apply the service-only boundary to those
-- current signatures as part of the same schema repair.
REVOKE ALL ON FUNCTION public.apply_event_change_proposal(
    uuid, uuid, uuid, text, text, timestamptz, timestamptz, boolean,
    text, text, text, text, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.reject_event_change_proposal(
    uuid, uuid, uuid, text, boolean, text, text, timestamptz, timestamptz,
    boolean, text, text, text, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.reopen_event_change_proposal(
    uuid, uuid, uuid, text, text, jsonb, text, boolean
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.apply_event_change_proposal(
    uuid, uuid, uuid, text, text, timestamptz, timestamptz, boolean,
    text, text, text, text, text
) TO service_role;
GRANT EXECUTE ON FUNCTION public.reject_event_change_proposal(
    uuid, uuid, uuid, text, boolean, text, text, timestamptz, timestamptz,
    boolean, text, text, text, text
) TO service_role;
GRANT EXECUTE ON FUNCTION public.reopen_event_change_proposal(
    uuid, uuid, uuid, text, text, jsonb, text, boolean
) TO service_role;

REVOKE ALL ON FUNCTION public.commit_email_extraction(uuid, text, bigint, jsonb, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.commit_email_extraction(uuid, text, bigint, jsonb, text) TO service_role;

COMMENT ON FUNCTION public.claim_due_email_sync(text, integer)
    IS 'Generation-fenced provider discovery claim; run-table columns are qualified to avoid OUT-parameter shadowing';
COMMENT ON FUNCTION public.claim_due_email_reconciliation(text, integer)
    IS 'Generation-fenced reconciliation claim; run-table columns are qualified to avoid OUT-parameter shadowing';

-- S5 made calendar_work_items authoritative but retained events.status as the
-- user-facing lifecycle projection. Claiming a queued item must move that
-- projection to syncing in the same transaction as the lease claim.
CREATE OR REPLACE FUNCTION public.claim_calendar_work_item(
    p_worker_id text, p_lease_seconds integer DEFAULT 300
) RETURNS SETOF public.calendar_work_items
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_item public.calendar_work_items;
BEGIN
    SELECT w.* INTO v_item
    FROM public.calendar_work_items w
    JOIN public.integrations i ON i.user_id = w.user_id
        AND i.provider = 'google_calendar' AND i.status = 'active'
    WHERE w.status = 'pending'
      AND w.attempts < w.max_attempts
      AND (w.next_retry_at IS NULL OR w.next_retry_at <= now())
    ORDER BY w.created_at ASC
    LIMIT 1
    FOR UPDATE OF w SKIP LOCKED;

    IF v_item.id IS NULL THEN
        SELECT w.* INTO v_item
        FROM public.calendar_work_items w
        JOIN public.integrations i ON i.user_id = w.user_id
            AND i.provider = 'google_calendar' AND i.status = 'active'
        WHERE w.status = 'processing'
          AND w.locked_until IS NOT NULL AND w.locked_until < now()
          AND w.attempts < w.max_attempts
        ORDER BY w.locked_until ASC
        LIMIT 1
        FOR UPDATE OF w SKIP LOCKED;
        IF v_item.id IS NOT NULL THEN
            UPDATE public.calendar_work_items
            SET status = 'pending', locked_by = NULL, locked_until = NULL, updated_at = now()
            WHERE id = v_item.id;
        END IF;
    END IF;

    IF v_item.id IS NULL THEN RETURN; END IF;

    UPDATE public.calendar_work_items
    SET status = 'processing', locked_by = p_worker_id,
        locked_until = now() + make_interval(secs => greatest(p_lease_seconds, 1)),
        attempts = attempts + 1, updated_at = now()
    WHERE id = v_item.id
    RETURNING * INTO v_item;

    UPDATE public.events
    SET status = 'syncing', updated_at = now()
    WHERE id = v_item.event_id;
    RETURN NEXT v_item;
END;
$$;

REVOKE ALL ON FUNCTION public.claim_calendar_work_item(text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claim_calendar_work_item(text, integer) TO service_role;

-- 20260826000001 simplified complete_calendar_work and regressed the
-- recoverable unsync transition. A worker-owned delete of a remote calendar
-- event must clear the provider identity and return the local event to New,
-- while an ordinary cancellation remains cancelled. Keep the event projection
-- fenced to the same lease and generation as the queue item.
CREATE OR REPLACE FUNCTION public.complete_calendar_work(
    p_item_id uuid, p_worker_id text, p_generation bigint,
    p_provider_event_id text, p_provider_revision text DEFAULT NULL
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_item public.calendar_work_items;
    v_updated integer;
    v_unsync boolean;
BEGIN
    SELECT * INTO v_item
    FROM public.calendar_work_items
    WHERE id = p_item_id
    FOR UPDATE;
    IF NOT FOUND OR v_item.status <> 'processing'
       OR v_item.locked_by IS DISTINCT FROM p_worker_id
       OR v_item.generation IS DISTINCT FROM p_generation THEN
        RETURN false;
    END IF;

    v_unsync := v_item.action = 'cancel'
        AND COALESCE((v_item.desired_event->>'delete_remote')::boolean, false);

    PERFORM set_config('selko.calendar_work_rpc', '1', true);
    UPDATE public.events
    SET status = CASE
            WHEN v_unsync THEN 'pending_review'
            WHEN v_item.action = 'cancel' THEN 'cancelled'
            ELSE 'synced'
        END,
        review_status = CASE
            WHEN v_unsync THEN 'pending_review'
            WHEN v_item.action = 'cancel' THEN 'cancelled'
            ELSE review_status
        END,
        google_calendar_event_id = CASE
            WHEN v_item.action = 'cancel' THEN NULL
            ELSE COALESCE(p_provider_event_id, google_calendar_event_id)
        END,
        synced_at = CASE
            WHEN v_item.action = 'cancel' THEN NULL
            ELSE now()
        END,
        updated_at = now()
    WHERE id = v_item.event_id
      AND status = 'syncing'
      AND EXISTS (
          SELECT 1
          FROM public.calendar_work_items current_item
          WHERE current_item.id = p_item_id
            AND current_item.status = 'processing'
            AND current_item.locked_by = p_worker_id
            AND current_item.generation = p_generation
      );
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 1 THEN
        RETURN false;
    END IF;

    UPDATE public.calendar_work_items
    SET status = 'succeeded',
        provider_event_id = COALESCE(p_provider_event_id, provider_event_id),
        expected_provider_revision = COALESCE(p_provider_revision, expected_provider_revision),
        locked_by = NULL,
        locked_until = NULL,
        updated_at = now(),
        completed_at = now()
    WHERE id = p_item_id;
    RETURN true;
END;
$$;

REVOKE ALL ON FUNCTION public.complete_calendar_work(uuid, text, bigint, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.complete_calendar_work(uuid, text, bigint, text, text) TO service_role;

-- A superseded recovery can retain the old worker lock after reauthorization.
-- Do not let that stale generation transition back to waiting and collide
-- with the newly-created active recovery generation.
CREATE OR REPLACE FUNCTION public.requeue_calendar_recovery_batch(
    p_recovery_id uuid, p_worker_id text, p_batch_size integer DEFAULT 100,
    p_max_batches integer DEFAULT 5
) RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_user_id uuid; v_tagged integer := 0; v_batch integer; v_batches integer := 0;
BEGIN
    SELECT user_id INTO v_user_id FROM public.integration_recoveries
    WHERE id = p_recovery_id
      AND status IN ('pending', 'processing', 'waiting')
      AND locked_by = p_worker_id AND locked_until > now();
    IF v_user_id IS NULL THEN RETURN -1; END IF;
    LOOP
        WITH batch AS (
            SELECT w.event_id FROM public.calendar_work_items w
            JOIN public.events e ON e.id = w.event_id
            WHERE e.user_id = v_user_id AND e.status IN ('approved', 'cancel_queued')
              AND w.failure_code IN ('oauth_required', 'oauth_scope_required')
              AND e.recovery_id IS NULL
            ORDER BY w.event_id LIMIT p_batch_size FOR UPDATE OF w SKIP LOCKED
        )
        UPDATE public.events SET recovery_id = p_recovery_id WHERE id IN (SELECT event_id FROM batch);
        GET DIAGNOSTICS v_batch = ROW_COUNT;
        v_tagged := v_tagged + v_batch;
        v_batches := v_batches + 1;
        EXIT WHEN v_batch < p_batch_size OR v_batches >= p_max_batches;
    END LOOP;
    UPDATE public.integration_recoveries
    SET discovered_count = discovered_count + v_tagged,
        requeued_count = requeued_count + v_tagged, updated_at = now()
    WHERE id = p_recovery_id;
    UPDATE public.integration_recoveries
    SET status = 'waiting', remaining_count = (
        SELECT count(*) FROM public.events
        WHERE recovery_id = p_recovery_id AND status IN ('approved', 'syncing', 'cancel_queued')
    ), locked_by = NULL, locked_until = NULL, updated_at = now()
    WHERE id = p_recovery_id;
    RETURN v_tagged;
END;
$$;

REVOKE ALL ON FUNCTION public.requeue_calendar_recovery_batch(uuid, text, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.requeue_calendar_recovery_batch(uuid, text, integer, integer) TO service_role;
