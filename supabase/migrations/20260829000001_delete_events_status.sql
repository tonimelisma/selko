-- V8 / D1(a): remove the legacy event-level delivery state.
--
-- review_status owns the user's decision. calendar_work_items owns delivery,
-- retries, and provider-write fencing. The API and clients may still expose a
-- derived status for presentation, but no database column stores that second
-- state machine.

DO $$
DECLARE
    v_event public.events;
BEGIN
    -- Older synced rows predate the durable queue. Preserve their provider
    -- history before the legacy column is removed.
    FOR v_event IN
        SELECT e.*
        FROM public.events e
        WHERE e.status = 'synced'
          AND NOT EXISTS (
              SELECT 1 FROM public.calendar_work_items w WHERE w.event_id = e.id
          )
    LOOP
        INSERT INTO public.calendar_work_items (
            event_id, user_id, action, generation, status, desired_event,
            provider_event_id, attempts, max_attempts, created_at, updated_at,
            completed_at
        ) VALUES (
            v_event.id, v_event.user_id, 'upsert', 1, 'succeeded',
            jsonb_build_object(
                'title', v_event.title, 'start_datetime', v_event.start_datetime,
                'end_datetime', v_event.end_datetime, 'all_day', v_event.all_day,
                'location', v_event.location, 'description', v_event.description,
                'importance', v_event.importance, 'source_attribution', v_event.source_attribution
            ),
            v_event.google_calendar_event_id, 1, 3,
            v_event.updated_at, v_event.updated_at, v_event.synced_at
        );
    END LOOP;
END;
$$;

DROP TRIGGER IF EXISTS events_legacy_calendar_enqueue_compat ON public.events;
DROP TRIGGER IF EXISTS events_review_status_compat ON public.events;
DROP TRIGGER IF EXISTS trg_enforce_event_cancellation_transition ON public.events;
DROP TRIGGER IF EXISTS events_notify_approved ON public.events;
DROP TRIGGER IF EXISTS trg_events_broadcast_ins ON public.events;
DROP TRIGGER IF EXISTS trg_events_broadcast_upd ON public.events;
DROP TRIGGER IF EXISTS trg_events_broadcast_del ON public.events;

DROP FUNCTION IF EXISTS public.events_legacy_calendar_enqueue_compat();
DROP FUNCTION IF EXISTS public.events_review_status_compat();
DROP FUNCTION IF EXISTS public.enforce_event_cancellation_transition();
DROP FUNCTION IF EXISTS public.trg_events_broadcast();

DROP FUNCTION IF EXISTS public._enqueue_calendar_work(uuid, uuid, text, jsonb, text, boolean, text);
DROP FUNCTION IF EXISTS public.complete_calendar_work(uuid, text, bigint, text, text);
DROP FUNCTION IF EXISTS public.fail_calendar_work(uuid, text, bigint, text, text, boolean);
DROP FUNCTION IF EXISTS public.defer_calendar_work(uuid, text, bigint, timestamptz, text);
DROP FUNCTION IF EXISTS public.apply_event_change_proposal(uuid, uuid, uuid, text, text, timestamptz, timestamptz, boolean, text, text, text, text, text);
DROP FUNCTION IF EXISTS public.reject_event_change_proposal(uuid, uuid, uuid, text, boolean, text, text, timestamptz, timestamptz, boolean, text, text, text, text);
DROP FUNCTION IF EXISTS public.reopen_event_change_proposal(uuid, uuid, uuid, text, text, jsonb, text, boolean);
DROP FUNCTION IF EXISTS public.ignore_sender_and_reject_pending(text, text);
DROP FUNCTION IF EXISTS public.undo_event_and_enqueue_calendar_work(uuid, uuid, text, jsonb, text, jsonb, text, boolean);
DROP FUNCTION IF EXISTS public.undo_event_and_enqueue_calendar_work(uuid, uuid, text, jsonb, text, boolean);
DROP FUNCTION IF EXISTS public.unsync_event_and_enqueue_calendar_work(uuid, uuid, text, boolean);
DROP FUNCTION IF EXISTS public.queue_event_cancellation(uuid, uuid);
DROP FUNCTION IF EXISTS public.commit_email_extraction(uuid, text, bigint, jsonb, text);
DROP FUNCTION IF EXISTS public.unlock_expired_event_locks();
DROP FUNCTION IF EXISTS public.requeue_calendar_recovery_batch(uuid, text, integer, integer);
DROP FUNCTION IF EXISTS public.refresh_waiting_calendar_recoveries(integer);

ALTER TABLE public.events DROP CONSTRAINT IF EXISTS events_status_check;
DROP INDEX IF EXISTS public.idx_events_user_status;
ALTER TABLE public.events DROP COLUMN status;

CREATE OR REPLACE FUNCTION public._enqueue_calendar_work(
    p_event_id uuid, p_user_id uuid, p_action text, p_desired_event jsonb,
    p_expected_provider_revision text, p_force_overwrite boolean, p_legacy_status text
) RETURNS public.calendar_work_items
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_event public.events; v_item public.calendar_work_items; v_generation bigint;
BEGIN
    IF p_action NOT IN ('upsert', 'cancel') THEN
        RAISE EXCEPTION 'invalid calendar work action %', p_action USING ERRCODE = '22023';
    END IF;
    IF p_action = 'upsert' AND p_desired_event IS NULL THEN
        RAISE EXCEPTION 'upsert calendar work requires desired_event' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_event FROM public.events
    WHERE id = p_event_id AND user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'event % is not owned by user %', p_event_id, p_user_id USING ERRCODE = '42501';
    END IF;
    SELECT COALESCE(max(generation), 0) + 1 INTO v_generation
    FROM public.calendar_work_items WHERE event_id = p_event_id;
    UPDATE public.calendar_work_items
    SET status = 'superseded', updated_at = now(), completed_at = now()
    WHERE event_id = p_event_id AND status IN ('pending', 'processing');
    INSERT INTO public.calendar_work_items (
        event_id, user_id, action, generation, desired_event,
        provider_event_id, expected_provider_revision, force_overwrite,
        attempts, max_attempts
    ) VALUES (
        p_event_id, p_user_id, p_action, v_generation, p_desired_event,
        v_event.google_calendar_event_id, p_expected_provider_revision,
        COALESCE(p_force_overwrite, false), 0, 3
    ) RETURNING * INTO v_item;
    UPDATE public.events
    SET review_status = CASE
        WHEN review_status IN ('pending_review', 'rejected', 'cancelled') THEN 'active'
        ELSE review_status
    END, updated_at = now()
    WHERE id = p_event_id;
    RETURN v_item;
END;
$$;

CREATE OR REPLACE FUNCTION public.set_event_review_status(
    p_event_id uuid, p_review_status text, p_user_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_event public.events;
    v_item public.calendar_work_items;
BEGIN
    IF p_review_status NOT IN ('active', 'rejected') THEN
        RAISE EXCEPTION 'invalid event review status %', p_review_status USING ERRCODE = '22023';
    END IF;
    IF p_user_id IS NOT NULL AND auth.uid() IS NOT NULL AND p_user_id <> auth.uid() THEN
        RAISE EXCEPTION 'event % is not owned by the caller', p_event_id USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_event FROM public.events
    WHERE id = p_event_id AND user_id = COALESCE(p_user_id, auth.uid()) FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'event % is not owned by the caller', p_event_id USING ERRCODE = '42501';
    END IF;
    IF p_review_status = 'active' THEN
        v_item := public._enqueue_calendar_work(
            p_event_id, v_event.user_id, 'upsert',
            jsonb_build_object(
                'title', v_event.title, 'start_datetime', v_event.start_datetime,
                'end_datetime', v_event.end_datetime, 'all_day', v_event.all_day,
                'location', v_event.location, 'description', v_event.description,
                'importance', v_event.importance, 'source_attribution', v_event.source_attribution
            ), NULL, false, 'approved'
        );
    ELSE
        UPDATE public.events SET review_status = 'rejected', updated_at = now()
        WHERE id = p_event_id;
    END IF;
    RETURN jsonb_build_object(
        'event_id', p_event_id, 'review_status', p_review_status,
        'work_item_id', v_item.id, 'generation', v_item.generation
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.complete_calendar_work(
    p_item_id uuid, p_worker_id text, p_generation bigint,
    p_provider_event_id text, p_provider_revision text DEFAULT NULL
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_item public.calendar_work_items;
BEGIN
    SELECT * INTO v_item FROM public.calendar_work_items WHERE id = p_item_id FOR UPDATE;
    IF NOT FOUND OR v_item.status <> 'processing' OR v_item.locked_by IS DISTINCT FROM p_worker_id
       OR v_item.generation IS DISTINCT FROM p_generation THEN RETURN false; END IF;
    UPDATE public.events SET
        google_calendar_event_id = CASE WHEN v_item.action = 'cancel' THEN NULL ELSE COALESCE(p_provider_event_id, google_calendar_event_id) END,
        synced_at = CASE WHEN v_item.action = 'cancel' THEN NULL ELSE now() END,
        review_status = CASE WHEN v_item.action = 'cancel' THEN 'cancelled' ELSE review_status END,
        updated_at = now()
    WHERE id = v_item.event_id;
    UPDATE public.calendar_work_items SET status = 'succeeded',
        provider_event_id = COALESCE(p_provider_event_id, provider_event_id),
        expected_provider_revision = COALESCE(p_provider_revision, expected_provider_revision),
        locked_by = NULL, locked_until = NULL, updated_at = now(), completed_at = now()
    WHERE id = p_item_id;
    RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION public.fail_calendar_work(
    p_item_id uuid, p_worker_id text, p_generation bigint, p_error_code text,
    p_error_detail text DEFAULT NULL, p_retryable boolean DEFAULT true
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_item public.calendar_work_items; v_status text; v_delivery_status text;
BEGIN
    SELECT * INTO v_item FROM public.calendar_work_items WHERE id = p_item_id FOR UPDATE;
    IF NOT FOUND OR v_item.status <> 'processing' OR v_item.locked_by IS DISTINCT FROM p_worker_id
       OR v_item.generation IS DISTINCT FROM p_generation THEN RETURN jsonb_build_object('fenced', true); END IF;
    IF p_retryable AND v_item.attempts < v_item.max_attempts THEN
        v_status := 'pending';
        UPDATE public.calendar_work_items SET status = 'pending', failure_code = left(p_error_code, 100),
            failure_detail = left(p_error_detail, 500), locked_by = NULL, locked_until = NULL,
            next_retry_at = now() + make_interval(secs => least(1800, greatest(60, 60 * power(2, least(attempts - 1, 5))::integer))), updated_at = now()
        WHERE id = p_item_id;
        v_delivery_status := CASE WHEN v_item.action = 'cancel' THEN 'cancel_queued' ELSE 'approved' END;
    ELSE
        v_status := CASE WHEN p_retryable THEN 'failed' ELSE 'blocked' END;
        v_delivery_status := CASE WHEN p_error_code IN ('oauth_required', 'oauth_scope_required')
            THEN CASE WHEN v_item.action = 'cancel' THEN 'cancel_queued' ELSE 'approved' END
            ELSE 'sync_failed' END;
        UPDATE public.calendar_work_items SET status = v_status, failure_code = left(p_error_code, 100),
            failure_detail = left(p_error_detail, 500), locked_by = NULL, locked_until = NULL,
            completed_at = now(), updated_at = now() WHERE id = p_item_id;
    END IF;
    UPDATE public.events SET updated_at = now() WHERE id = v_item.event_id;
    RETURN jsonb_build_object('fenced', false, 'status', v_status, 'event_status', v_delivery_status);
END;
$$;

CREATE OR REPLACE FUNCTION public.defer_calendar_work(
    p_item_id uuid, p_worker_id text, p_generation bigint,
    p_next_retry_at timestamptz, p_detail text DEFAULT 'calendar quota exceeded'
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_item public.calendar_work_items;
BEGIN
    SELECT * INTO v_item FROM public.calendar_work_items WHERE id = p_item_id FOR UPDATE;
    IF NOT FOUND OR v_item.status <> 'processing' OR v_item.locked_by IS DISTINCT FROM p_worker_id
       OR v_item.generation IS DISTINCT FROM p_generation THEN RETURN false; END IF;
    UPDATE public.calendar_work_items SET status = 'pending', attempts = greatest(attempts - 1, 0),
        failure_code = 'calendar_quota', failure_detail = left(p_detail, 500), locked_by = NULL,
        locked_until = NULL, next_retry_at = p_next_retry_at, updated_at = now() WHERE id = p_item_id;
    UPDATE public.events SET updated_at = now() WHERE id = v_item.event_id;
    RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION public.apply_event_change_proposal(
    p_event_id uuid, p_user_id uuid, p_proposal_id uuid, p_expected_hash text,
    p_title text, p_start_datetime timestamptz, p_end_datetime timestamptz,
    p_all_day boolean, p_location text, p_description text, p_importance text,
    p_next_status text, p_calendar_sync_action text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_event public.events; v_proposal public.event_change_proposals; v_item public.calendar_work_items;
BEGIN
    SELECT * INTO v_event FROM public.events WHERE id = p_event_id AND user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'event % is not owned by user %', p_event_id, p_user_id; END IF;
    v_proposal := public._lock_owned_pending_proposal(p_event_id, p_user_id, p_proposal_id, p_expected_hash);
    IF p_next_status NOT IN ('approved', 'cancel_queued', 'cancelled')
       OR p_calendar_sync_action NOT IN ('upsert', 'cancel') THEN
        RAISE EXCEPTION 'invalid proposal application state' USING ERRCODE = '22023';
    END IF;
    UPDATE public.events SET title = p_title, start_datetime = p_start_datetime,
        end_datetime = p_end_datetime, all_day = p_all_day, location = p_location,
        description = p_description, importance = p_importance,
        review_status = CASE WHEN p_next_status = 'cancelled' THEN 'cancelled' ELSE 'active' END,
        updated_at = now() WHERE id = p_event_id;
    UPDATE public.event_change_proposals SET status = 'applied', resolution_reason = 'user_applied',
        resolved_at = now(), updated_at = now() WHERE id = v_proposal.id;
    IF p_next_status IN ('approved', 'cancel_queued') THEN
        v_item := public._enqueue_calendar_work(
            p_event_id, p_user_id, p_calendar_sync_action,
            CASE WHEN p_calendar_sync_action = 'cancel' THEN NULL ELSE jsonb_build_object(
                'title', p_title, 'start_datetime', p_start_datetime,
                'end_datetime', p_end_datetime, 'all_day', p_all_day,
                'location', p_location, 'description', p_description,
                'importance', p_importance
            ) END, NULL, false, p_next_status
        );
    END IF;
    RETURN jsonb_build_object('event_id', p_event_id, 'proposal_id', v_proposal.id,
        'status', p_next_status, 'calendar_work_id', v_item.id);
END;
$$;

CREATE OR REPLACE FUNCTION public.reject_event_change_proposal(
    p_event_id uuid, p_user_id uuid, p_proposal_id uuid, p_expected_hash text,
    p_delete_event boolean, p_restore_status text, p_title text,
    p_start_datetime timestamptz, p_end_datetime timestamptz, p_all_day boolean,
    p_location text, p_description text, p_importance text, p_resolution_reason text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_event public.events; v_proposal public.event_change_proposals; v_review_status text;
BEGIN
    SELECT * INTO v_event FROM public.events WHERE id = p_event_id AND user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'event % is not owned by user %', p_event_id, p_user_id; END IF;
    v_proposal := public._lock_owned_pending_proposal(p_event_id, p_user_id, p_proposal_id, p_expected_hash);
    IF p_resolution_reason NOT IN ('user_rejected', 'repair_operator') THEN
        RAISE EXCEPTION 'invalid proposal rejection reason' USING ERRCODE = '22023';
    END IF;
    IF p_delete_event THEN
        IF v_event.google_calendar_event_id IS NULL OR v_event.synced_at IS NOT NULL THEN
            RAISE EXCEPTION 'event % is not an unsynced calendar-only proposal', p_event_id;
        END IF;
        DELETE FROM public.event_change_proposals WHERE id = v_proposal.id;
        DELETE FROM public.events WHERE id = p_event_id;
        RETURN jsonb_build_object('event_id', p_event_id, 'proposal_id', v_proposal.id, 'status', 'deleted');
    END IF;
    IF p_restore_status NOT IN ('pending_review', 'approved', 'synced', 'sync_failed', 'rejected', 'cancelled') THEN
        RAISE EXCEPTION 'invalid restored status %', p_restore_status USING ERRCODE = '22023';
    END IF;
    v_review_status := CASE WHEN p_restore_status = 'pending_review' THEN 'pending_review'
        WHEN p_restore_status = 'rejected' THEN 'rejected'
        WHEN p_restore_status = 'cancelled' THEN 'cancelled' ELSE 'active' END;
    UPDATE public.event_change_proposals SET status = 'rejected', resolution_reason = p_resolution_reason,
        resolved_at = now(), updated_at = now() WHERE id = v_proposal.id;
    UPDATE public.events SET review_status = v_review_status,
        title = p_title, start_datetime = p_start_datetime, end_datetime = p_end_datetime,
        all_day = p_all_day, location = p_location, description = p_description,
        importance = p_importance, updated_at = now() WHERE id = p_event_id;
    RETURN jsonb_build_object('event_id', p_event_id, 'proposal_id', v_proposal.id, 'status', p_restore_status);
END;
$$;

CREATE OR REPLACE FUNCTION public.reopen_event_change_proposal(
    p_event_id uuid, p_user_id uuid, p_proposal_id uuid, p_expected_hash text,
    p_action text DEFAULT NULL, p_desired_event jsonb DEFAULT NULL,
    p_expected_provider_revision text DEFAULT NULL, p_force_overwrite boolean DEFAULT false
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_event public.events; v_proposal public.event_change_proposals; v_item public.calendar_work_items;
BEGIN
    SELECT * INTO v_event FROM public.events WHERE id = p_event_id AND user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'event % is not owned', p_event_id; END IF;
    SELECT p.* INTO v_proposal FROM public.event_change_proposals p
    WHERE p.id = p_proposal_id AND p.event_id = p_event_id AND p.user_id = p_user_id FOR UPDATE;
    IF NOT FOUND OR v_proposal.status <> 'applied' THEN
        RAISE EXCEPTION 'proposal % is not an applied proposal', p_proposal_id;
    END IF;
    IF p_expected_hash IS NOT NULL AND public.event_change_proposal_hash(v_proposal) <> p_expected_hash THEN
        RAISE EXCEPTION 'proposal % changed before reopen', p_proposal_id USING ERRCODE = '40001';
    END IF;
    UPDATE public.event_change_proposals SET status = 'pending', resolution_reason = NULL,
        resolved_at = NULL, updated_at = now() WHERE id = v_proposal.id;
    UPDATE public.events SET title = v_proposal.event_snapshot_before->>'title',
        start_datetime = NULLIF(v_proposal.event_snapshot_before->>'start_datetime', '')::timestamptz,
        end_datetime = NULLIF(v_proposal.event_snapshot_before->>'end_datetime', '')::timestamptz,
        all_day = COALESCE((v_proposal.event_snapshot_before->>'all_day')::boolean, false),
        location = v_proposal.event_snapshot_before->>'location',
        description = v_proposal.event_snapshot_before->>'description',
        importance = COALESCE(v_proposal.event_snapshot_before->>'importance', importance),
        review_status = 'active', updated_at = now() WHERE id = p_event_id;
    IF p_action IS NOT NULL THEN
        v_item := public._enqueue_calendar_work(p_event_id, p_user_id, p_action, p_desired_event,
            p_expected_provider_revision, p_force_overwrite,
            CASE WHEN p_action = 'cancel' THEN 'cancel_queued' ELSE 'approved' END);
    END IF;
    RETURN jsonb_build_object('event_id', p_event_id, 'proposal_id', v_proposal.id,
        'status', 'active', 'calendar_work', to_jsonb(v_item));
END;
$$;

CREATE OR REPLACE FUNCTION public.ignore_sender_and_reject_pending(
    p_sender_email text DEFAULT NULL,
    p_sender_domain text DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER AS $$
DECLARE
    v_user_id uuid := auth.uid();
    v_rejected_new integer := 0;
    v_discarded_changes integer := 0;
    v_proposal record;
    v_snapshot jsonb;
    v_restore_status text;
BEGIN
    IF v_user_id IS NULL THEN RAISE EXCEPTION 'not authenticated'; END IF;
    IF p_sender_email IS NULL AND p_sender_domain IS NULL THEN
        RAISE EXCEPTION 'sender_email or sender_domain required';
    END IF;
    IF p_sender_email IS NOT NULL THEN
        INSERT INTO public.sender_rules (user_id, sender_email, action)
        VALUES (v_user_id, p_sender_email, 'ignore')
        ON CONFLICT (user_id, sender_email) WHERE sender_email IS NOT NULL
        DO UPDATE SET action = 'ignore', updated_at = now();
    ELSE
        INSERT INTO public.sender_rules (user_id, sender_domain, action)
        VALUES (v_user_id, p_sender_domain, 'ignore')
        ON CONFLICT (user_id, sender_domain) WHERE sender_domain IS NOT NULL
        DO UPDATE SET action = 'ignore', updated_at = now();
    END IF;

    WITH matching AS (
        SELECT DISTINCT s.event_id
        FROM public.event_sources s JOIN public.emails m ON m.id = s.email_id
        WHERE m.user_id = v_user_id
          AND ((p_sender_email IS NOT NULL AND m.from_email = p_sender_email)
            OR (p_sender_domain IS NOT NULL AND m.from_email LIKE '%@' || p_sender_domain))
    )
    UPDATE public.events e SET review_status = 'rejected', updated_at = now()
    FROM matching WHERE e.id = matching.event_id AND e.user_id = v_user_id
      AND e.review_status = 'pending_review';
    GET DIAGNOSTICS v_rejected_new = ROW_COUNT;

    FOR v_proposal IN
        SELECT p.*, e.google_calendar_event_id AS event_google_calendar_event_id,
               e.synced_at, e.title AS event_title, e.start_datetime AS event_start,
               e.end_datetime AS event_end, e.all_day AS event_all_day,
               e.location AS event_location, e.description AS event_description,
               e.importance AS event_importance
        FROM public.event_change_proposals p
        JOIN public.events e ON e.id = p.event_id
        JOIN public.event_sources s ON s.id = p.source_id
        JOIN public.emails m ON m.id = s.email_id
        WHERE p.user_id = v_user_id AND p.status = 'pending' AND e.review_status = 'active'
          AND ((p_sender_email IS NOT NULL AND m.from_email = p_sender_email)
            OR (p_sender_domain IS NOT NULL AND m.from_email LIKE '%@' || p_sender_domain))
        FOR UPDATE OF p, e
    LOOP
        v_snapshot := v_proposal.event_snapshot_before;
        v_restore_status := CASE
            WHEN v_snapshot ? 'review_status' AND (v_snapshot->>'review_status') IN
                ('pending_review', 'active', 'rejected', 'cancelled')
                THEN CASE WHEN v_snapshot->>'review_status' = 'active' THEN 'approved'
                    ELSE v_snapshot->>'review_status' END
            WHEN v_snapshot ? 'status' AND (v_snapshot->>'status') IN
                ('pending_review', 'approved', 'synced', 'sync_failed', 'rejected', 'cancelled')
                THEN CASE WHEN (v_snapshot->>'status') IN ('pending_review', 'rejected', 'cancelled')
                    THEN v_snapshot->>'status' ELSE 'active' END
            WHEN v_proposal.event_google_calendar_event_id IS NOT NULL THEN 'synced'
            ELSE 'approved'
        END;
        PERFORM public.reject_event_change_proposal(
            v_proposal.event_id, v_user_id, v_proposal.id, NULL, false,
            v_restore_status,
            COALESCE(v_snapshot->>'title', v_proposal.event_title),
            COALESCE(NULLIF(v_snapshot->>'start_datetime', '')::timestamptz, v_proposal.event_start),
            COALESCE(NULLIF(v_snapshot->>'end_datetime', '')::timestamptz, v_proposal.event_end),
            COALESCE((v_snapshot->>'all_day')::boolean, v_proposal.event_all_day),
            CASE WHEN v_snapshot ? 'location' THEN v_snapshot->>'location' ELSE v_proposal.event_location END,
            CASE WHEN v_snapshot ? 'description' THEN v_snapshot->>'description' ELSE v_proposal.event_description END,
            COALESCE(v_snapshot->>'importance', v_proposal.event_importance), 'repair_operator'
        );
        v_discarded_changes := v_discarded_changes + 1;
    END LOOP;
    RETURN jsonb_build_object('rejected_new', v_rejected_new, 'discarded_changes', v_discarded_changes);
END;
$$;

CREATE OR REPLACE FUNCTION public.undo_event_and_enqueue_calendar_work(
    p_event_id uuid, p_user_id uuid, p_action text DEFAULT NULL,
    p_desired_event jsonb DEFAULT NULL, p_expected_provider_revision text DEFAULT NULL,
    p_force_overwrite boolean DEFAULT false
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_event public.events; v_item public.calendar_work_items;
BEGIN
    SELECT * INTO v_event FROM public.events
    WHERE id = p_event_id AND user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'event % is not owned by user %', p_event_id, p_user_id; END IF;
    IF p_action IS NOT NULL THEN
        v_item := public._enqueue_calendar_work(p_event_id, p_user_id, p_action, p_desired_event,
            p_expected_provider_revision, p_force_overwrite,
            CASE WHEN p_action = 'cancel' THEN 'cancel_queued' ELSE 'approved' END);
    END IF;
    UPDATE public.events SET review_status = 'pending_review', updated_at = now()
    WHERE id = p_event_id;
    RETURN jsonb_build_object('status', 'pending_review', 'work_item_id', v_item.id,
        'generation', v_item.generation);
END;
$$;

CREATE OR REPLACE FUNCTION public.unsync_event_and_enqueue_calendar_work(
    p_event_id uuid, p_user_id uuid, p_expected_provider_revision text DEFAULT NULL,
    p_force_overwrite boolean DEFAULT false
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_event public.events; v_item public.calendar_work_items;
BEGIN
    SELECT * INTO v_event FROM public.events
    WHERE id = p_event_id AND user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'event % is not owned by user %', p_event_id, p_user_id; END IF;
    IF v_event.google_calendar_event_id IS NULL OR NOT EXISTS (
        SELECT 1 FROM public.calendar_work_items w
        WHERE w.event_id = p_event_id AND w.action = 'upsert' AND w.status = 'succeeded'
    ) THEN
        RAISE EXCEPTION 'event % is not synced', p_event_id USING ERRCODE = '22023';
    END IF;
    v_item := public._enqueue_calendar_work(p_event_id, p_user_id, 'cancel',
        '{"delete_remote": true}'::jsonb, p_expected_provider_revision, p_force_overwrite, 'cancel_queued');
    UPDATE public.events SET review_status = 'pending_review', updated_at = now() WHERE id = p_event_id;
    RETURN jsonb_build_object('status', 'pending_review', 'work_item_id', v_item.id, 'generation', v_item.generation);
END;
$$;

CREATE OR REPLACE FUNCTION public.queue_event_cancellation(p_event_id uuid, p_user_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_event public.events; v_item public.calendar_work_items;
BEGIN
    SELECT * INTO v_event FROM public.events WHERE id = p_event_id AND user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'event % is not owned by user %', p_event_id, p_user_id; END IF;
    IF v_event.review_status = 'cancelled' THEN
        RETURN jsonb_build_object('event_id', p_event_id, 'status', 'cancelled', 'already_cancelled', true);
    END IF;
    IF v_event.review_status = 'rejected' OR EXISTS (
        SELECT 1 FROM public.calendar_work_items w
        WHERE w.event_id = p_event_id AND w.status = 'processing'
    ) THEN
        RAISE EXCEPTION 'event % cannot be cancelled in its current state', p_event_id;
    END IF;
    v_item := public._enqueue_calendar_work(p_event_id, p_user_id, 'cancel', NULL, NULL, false, 'cancel_queued');
    RETURN jsonb_build_object('event_id', p_event_id, 'status', 'cancel_queued',
        'work_item_id', v_item.id, 'generation', v_item.generation, 'already_cancelled', false);
END;
$$;

CREATE OR REPLACE FUNCTION public.trg_events_broadcast()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM public.broadcast_user_ui_change(NEW.user_id, 'events', 'INSERT', NEW.id);
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM public.broadcast_user_ui_change(OLD.user_id, 'events', 'DELETE', OLD.id);
    ELSIF NEW.review_status IS DISTINCT FROM OLD.review_status
       OR NEW.title IS DISTINCT FROM OLD.title
       OR NEW.start_datetime IS DISTINCT FROM OLD.start_datetime
       OR NEW.end_datetime IS DISTINCT FROM OLD.end_datetime THEN
        PERFORM public.broadcast_user_ui_change(NEW.user_id, 'events', 'UPDATE', NEW.id);
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE TRIGGER trg_events_broadcast_ins
    AFTER INSERT ON public.events FOR EACH ROW EXECUTE FUNCTION public.trg_events_broadcast();
CREATE TRIGGER trg_events_broadcast_upd
    AFTER UPDATE OF review_status, title, start_datetime, end_datetime ON public.events
    FOR EACH ROW EXECUTE FUNCTION public.trg_events_broadcast();
CREATE TRIGGER trg_events_broadcast_del
    AFTER DELETE ON public.events FOR EACH ROW EXECUTE FUNCTION public.trg_events_broadcast();

CREATE OR REPLACE FUNCTION public.trg_event_change_proposals_broadcast()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    PERFORM public.broadcast_user_ui_change(
        COALESCE(NEW.user_id, OLD.user_id), 'event_change_proposals', TG_OP,
        COALESCE(NEW.id, OLD.id)
    );
    RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE OR REPLACE FUNCTION public.trg_calendar_work_items_broadcast()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    PERFORM public.broadcast_user_ui_change(
        COALESCE(NEW.user_id, OLD.user_id), 'calendar_work_items', TG_OP,
        COALESCE(NEW.id, OLD.id)
    );
    RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS trg_event_change_proposals_broadcast ON public.event_change_proposals;
CREATE TRIGGER trg_event_change_proposals_broadcast
    AFTER INSERT OR UPDATE OR DELETE ON public.event_change_proposals
    FOR EACH ROW EXECUTE FUNCTION public.trg_event_change_proposals_broadcast();
DROP TRIGGER IF EXISTS trg_calendar_work_items_broadcast ON public.calendar_work_items;
CREATE TRIGGER trg_calendar_work_items_broadcast
    AFTER INSERT OR UPDATE OR DELETE ON public.calendar_work_items
    FOR EACH ROW EXECUTE FUNCTION public.trg_calendar_work_items_broadcast();

CREATE OR REPLACE FUNCTION public.commit_email_extraction(
    p_email_id uuid, p_worker_id text, p_generation bigint,
    p_decisions jsonb, p_terminal text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_email public.emails; v_decision jsonb; v_extra jsonb; v_hint jsonb;
    v_source jsonb; v_fields jsonb; v_action text; v_source_origin text;
    v_source_type text; v_event_id uuid; v_source_id uuid; v_google_source_id text;
    v_actual_fingerprint text; v_hint_fingerprint text; v_window_start timestamptz;
    v_window_end timestamptz; v_index integer; v_hint_kind text; v_hint_hash text;
    v_hint_recurrence text; v_hint_sequence integer; v_hint_dtstamp timestamptz;
    v_applied integer := 0; v_event_ids jsonb := '[]'::jsonb;
    v_change_set jsonb; v_snapshot jsonb; v_proposal_status text;
    v_review_status text; v_calendar_action text; v_auto_apply boolean;
BEGIN
    IF p_terminal NOT IN ('processed', 'skipped', 'failed') THEN
        RAISE EXCEPTION 'invalid extraction terminal status: %', p_terminal;
    END IF;
    SELECT * INTO v_email FROM public.emails WHERE id = p_email_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'email % not found', p_email_id; END IF;
    IF v_email.locked_by IS DISTINCT FROM p_worker_id OR v_email.lock_generation IS DISTINCT FROM p_generation THEN
        RETURN jsonb_build_object('fenced', true, 'applied', 0);
    END IF;

    FOR v_decision IN SELECT value FROM jsonb_array_elements(COALESCE(p_decisions, '[]'::jsonb)) AS item(value)
        WHERE value->>'action' <> 'noop' ORDER BY value->>'window_start', value->>'window_end'
    LOOP
        IF v_decision->>'action' NOT IN ('create', 'update', 'noop')
           OR v_decision->>'window_start' IS NULL OR v_decision->>'window_end' IS NULL THEN
            RAISE EXCEPTION 'invalid extraction decision envelope';
        END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended(v_email.user_id::text || '|' ||
            (v_decision->>'window_start') || '|' || (v_decision->>'window_end'), 0));
        FOR v_hint IN SELECT value FROM jsonb_array_elements(COALESCE(v_decision->'hints', '[]'::jsonb)) AS item(value)
            ORDER BY value->>'kind', value->>'value_hash', value->>'recurrence_id'
        LOOP
            PERFORM pg_advisory_xact_lock(hashtextextended(v_email.user_id::text || '|hint|' ||
                (v_hint->>'kind') || '|' || (v_hint->>'value_hash') || '|' || COALESCE(v_hint->>'recurrence_id', ''), 0));
        END LOOP;
    END LOOP;

    IF jsonb_array_length(COALESCE(p_decisions, '[]'::jsonb)) > 0 THEN
        FOR v_index IN 0..jsonb_array_length(COALESCE(p_decisions, '[]'::jsonb)) - 1 LOOP
            v_decision := p_decisions->v_index;
            IF v_decision->>'action' = 'noop' THEN CONTINUE; END IF;
            v_window_start := (v_decision->>'window_start')::timestamptz;
            v_window_end := (v_decision->>'window_end')::timestamptz;
            SELECT md5(COALESCE(string_agg(e.id::text || ':' || to_char(e.updated_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), ',' ORDER BY e.id), '')) INTO v_actual_fingerprint
            FROM public.events e WHERE e.user_id = v_email.user_id
              AND e.start_datetime >= v_window_start AND e.start_datetime < v_window_end;
            IF v_actual_fingerprint IS DISTINCT FROM v_decision->>'expected_fingerprint' THEN
                RETURN jsonb_build_object('fenced', false, 'conflict', true, 'conflicting_indexes', jsonb_build_array(v_index));
            END IF;
            IF jsonb_array_length(COALESCE(v_decision->'hint_keys', '[]'::jsonb)) > 0 THEN
                SELECT md5(COALESCE(string_agg(e.id::text || ':' || to_char(e.updated_at AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), ',' ORDER BY e.id), '')) INTO v_hint_fingerprint
                FROM public.events e WHERE e.user_id = v_email.user_id AND e.id IN (
                    SELECT DISTINCT h.event_id FROM public.event_identity_hints h
                    WHERE h.user_id = v_email.user_id AND format('%s|%s|%s', h.kind, h.value_hash, h.recurrence_id)
                        IN (SELECT value::text FROM jsonb_array_elements_text(v_decision->'hint_keys')));
                IF v_hint_fingerprint IS DISTINCT FROM v_decision->>'expected_hint_fingerprint' THEN
                    RETURN jsonb_build_object('fenced', false, 'conflict', true, 'conflicting_indexes', jsonb_build_array(v_index));
                END IF;
            END IF;
        END LOOP;
    END IF;

    FOR v_decision IN SELECT value FROM jsonb_array_elements(COALESCE(p_decisions, '[]'::jsonb)) AS item(value) LOOP
        v_action := v_decision->>'action'; IF v_action = 'noop' THEN CONTINUE; END IF;
        v_fields := COALESCE(v_decision->'fields', '{}'::jsonb);
        v_source := COALESCE(v_decision->'source', '{}'::jsonb);
        v_source_origin := COALESCE(v_source->>'source_origin', 'email');
        v_source_type := COALESCE(v_source->>'source_type', 'new_invitation');
        v_google_source_id := v_source->>'google_calendar_source_event_id';
        v_change_set := v_source->'change_set'; v_snapshot := v_source->'event_snapshot_before';
        v_review_status := COALESCE(v_fields->>'review_status', CASE
            WHEN v_fields->>'status' = 'pending_review' THEN 'pending_review'
            WHEN v_fields->>'status' = 'rejected' THEN 'rejected'
            WHEN v_fields->>'status' = 'cancelled' THEN 'cancelled'
            ELSE 'active' END);
        v_calendar_action := COALESCE(v_fields->>'calendar_action', CASE
            WHEN v_fields->>'status' = 'cancel_queued' THEN 'cancel' ELSE 'upsert' END);
        IF v_review_status NOT IN ('pending_review', 'active', 'rejected', 'cancelled')
           OR v_calendar_action NOT IN ('upsert', 'cancel') THEN
            RAISE EXCEPTION 'invalid extraction review or calendar state';
        END IF;
        v_auto_apply := v_review_status = 'active';

        IF v_action = 'create' THEN
            INSERT INTO public.events (
                user_id, title, start_datetime, end_datetime, all_day, location, description,
                importance, review_status, recurrence_rule, google_calendar_event_id
            ) VALUES (
                v_email.user_id, v_fields->>'title', (v_fields->>'start_datetime')::timestamptz,
                (v_fields->>'end_datetime')::timestamptz, COALESCE((v_fields->>'all_day')::boolean, false),
                v_fields->>'location', v_fields->>'description', COALESCE(v_fields->>'importance', 'action_required'),
                v_review_status, v_fields->>'recurrence_rule', v_fields->>'google_calendar_event_id'
            ) RETURNING id INTO v_event_id;
            v_event_ids := v_event_ids || to_jsonb(v_event_id);
        ELSE
            v_event_id := (v_decision->>'event_id')::uuid;
            IF v_event_id IS NULL THEN RAISE EXCEPTION 'update decision requires event_id'; END IF;
            PERFORM 1 FROM public.events WHERE id = v_event_id AND user_id = v_email.user_id FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'event % is not owned by email user', v_event_id; END IF;
            IF v_auto_apply OR v_change_set IS NULL THEN
                UPDATE public.events SET
                    title = CASE WHEN v_fields ? 'title' THEN v_fields->>'title' ELSE title END,
                    start_datetime = CASE WHEN v_fields ? 'start_datetime' THEN (v_fields->>'start_datetime')::timestamptz ELSE start_datetime END,
                    end_datetime = CASE WHEN v_fields ? 'end_datetime' THEN (v_fields->>'end_datetime')::timestamptz ELSE end_datetime END,
                    all_day = CASE WHEN v_fields ? 'all_day' THEN (v_fields->>'all_day')::boolean ELSE all_day END,
                    location = CASE WHEN v_fields ? 'location' THEN v_fields->>'location' ELSE location END,
                    description = CASE WHEN v_fields ? 'description' THEN v_fields->>'description' ELSE description END,
                    importance = CASE WHEN v_fields ? 'importance' THEN v_fields->>'importance' ELSE importance END,
                    review_status = v_review_status,
                    recurrence_rule = CASE WHEN v_fields ? 'recurrence_rule' THEN v_fields->>'recurrence_rule' ELSE recurrence_rule END,
                    updated_at = now() WHERE id = v_event_id;
            ELSE
                UPDATE public.events SET review_status = 'active', updated_at = now() WHERE id = v_event_id;
            END IF;
        END IF;

        IF v_source_origin = 'google_calendar' THEN
            INSERT INTO public.event_sources(event_id, source_origin, google_calendar_source_event_id, source_type, extracted_data)
            VALUES(v_event_id, v_source_origin, v_google_source_id, v_source_type, COALESCE(v_source->'extracted_data', '{}'::jsonb))
            RETURNING id INTO v_source_id;
        ELSE
            INSERT INTO public.event_sources(event_id, email_id, source_origin, source_type, extracted_data)
            VALUES(v_event_id, COALESCE((v_source->>'email_id')::uuid, p_email_id), v_source_origin, v_source_type,
                COALESCE(v_source->'extracted_data', '{}'::jsonb))
            ON CONFLICT (event_id, email_id) WHERE source_origin = 'email' DO UPDATE SET
                source_type = EXCLUDED.source_type, extracted_data = EXCLUDED.extracted_data
            RETURNING id INTO v_source_id;
        END IF;

        FOR v_extra IN SELECT value FROM jsonb_array_elements(COALESCE(v_source->'extra_sources', '[]'::jsonb)) AS item(value) LOOP
            IF COALESCE(v_extra->>'source_origin', 'email') = 'google_calendar' THEN
                INSERT INTO public.event_sources(event_id, source_origin, google_calendar_source_event_id, source_type, extracted_data)
                VALUES(v_event_id, 'google_calendar', v_extra->>'google_calendar_source_event_id',
                    COALESCE(v_extra->>'source_type', v_source_type), COALESCE(v_extra->'extracted_data', '{}'::jsonb));
            END IF;
        END LOOP;

        IF jsonb_typeof(v_change_set) = 'object' AND v_change_set <> '{}'::jsonb
           AND jsonb_typeof(v_snapshot) = 'object' AND v_snapshot <> '{}'::jsonb THEN
            UPDATE public.event_change_proposals SET status = 'superseded', resolution_reason = 'superseded_by_newer_proposal',
                resolved_at = now(), updated_at = now() WHERE event_id = v_event_id AND status = 'pending' AND source_id <> v_source_id;
            v_proposal_status := CASE WHEN v_auto_apply THEN 'applied' ELSE 'pending' END;
            INSERT INTO public.event_change_proposals(event_id, user_id, source_id, kind, status, change_set, event_snapshot_before, resolution_reason)
            VALUES(v_event_id, v_email.user_id, v_source_id,
                CASE WHEN v_source_type = 'cancellation' THEN 'cancellation' ELSE 'material_update' END,
                v_proposal_status, v_change_set, v_snapshot, CASE WHEN v_auto_apply THEN 'automatic_apply' ELSE NULL END)
            ON CONFLICT (source_id) DO UPDATE SET status = EXCLUDED.status, change_set = EXCLUDED.change_set,
                event_snapshot_before = EXCLUDED.event_snapshot_before, resolution_reason = EXCLUDED.resolution_reason,
                resolved_at = CASE WHEN EXCLUDED.status = 'pending' THEN NULL ELSE now() END, updated_at = now();
            IF NOT v_auto_apply THEN
                UPDATE public.events SET review_status = 'active' WHERE id = v_event_id;
            END IF;
        END IF;

        IF v_auto_apply THEN
            PERFORM public._enqueue_calendar_work(
                v_event_id, v_email.user_id, v_calendar_action,
                CASE WHEN v_calendar_action = 'cancel' THEN NULL ELSE jsonb_build_object(
                    'title', v_fields->>'title', 'start_datetime', v_fields->>'start_datetime',
                    'end_datetime', v_fields->>'end_datetime', 'all_day', COALESCE((v_fields->>'all_day')::boolean, false),
                    'location', v_fields->>'location', 'description', v_fields->>'description',
                    'importance', COALESCE(v_fields->>'importance', 'action_required')
                ) END, NULL, false, NULL
            );
        END IF;

        FOR v_hint IN SELECT value FROM jsonb_array_elements(COALESCE(v_decision->'hints', '[]'::jsonb)) AS item(value) LOOP
            v_hint_kind := v_hint->>'kind'; v_hint_hash := v_hint->>'value_hash';
            v_hint_recurrence := COALESCE(v_hint->>'recurrence_id', '');
            IF v_hint_kind NOT IN ('ical_uid', 'provider_thread', 'join_url', 'management_url')
               OR v_hint->>'strength' NOT IN ('authoritative', 'supporting') OR NULLIF(v_hint_hash, '') IS NULL THEN
                RAISE EXCEPTION 'invalid identity hint';
            END IF;
            v_hint_sequence := COALESCE(NULLIF(v_hint->>'sequence', '')::integer, 0);
            v_hint_dtstamp := NULLIF(v_hint->>'dtstamp', '')::timestamptz;
            INSERT INTO public.event_identity_hints(user_id, event_id, source_email_id, kind, value_hash, recurrence_id, strength, sequence, dtstamp)
            VALUES(v_email.user_id, v_event_id, p_email_id, v_hint_kind, v_hint_hash, v_hint_recurrence,
                v_hint->>'strength', v_hint_sequence, v_hint_dtstamp)
            ON CONFLICT (event_id, kind, value_hash, recurrence_id) DO UPDATE SET
                source_email_id = EXCLUDED.source_email_id, strength = EXCLUDED.strength,
                sequence = CASE WHEN EXCLUDED.kind = 'ical_uid' AND EXCLUDED.sequence >= event_identity_hints.sequence
                    THEN EXCLUDED.sequence ELSE event_identity_hints.sequence END,
                dtstamp = CASE WHEN EXCLUDED.kind = 'ical_uid' AND EXCLUDED.sequence >= event_identity_hints.sequence
                    THEN EXCLUDED.dtstamp ELSE event_identity_hints.dtstamp END;
        END LOOP;
        v_applied := v_applied + 1;
    END LOOP;
    UPDATE public.emails SET processing_status = p_terminal, processing_error = NULL,
        processed_at = CASE WHEN p_terminal = 'processed' THEN now() ELSE processed_at END,
        locked_by = NULL, locked_until = NULL WHERE id = p_email_id;
    RETURN jsonb_build_object('fenced', false, 'conflict', false, 'applied', v_applied, 'event_ids', v_event_ids);
END;
$$;

CREATE OR REPLACE FUNCTION public.unlock_expired_event_locks()
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_count integer;
BEGIN
    UPDATE public.calendar_work_items
    SET status = 'pending', locked_by = NULL, locked_until = NULL, updated_at = now()
    WHERE status = 'processing' AND locked_until < now();
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;

CREATE OR REPLACE FUNCTION public.requeue_calendar_recovery_batch(
    p_recovery_id uuid, p_worker_id text, p_batch_size integer DEFAULT 100,
    p_max_batches integer DEFAULT 5
) RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_user_id uuid; v_tagged integer := 0; v_batch integer; v_batches integer := 0;
BEGIN
    SELECT user_id INTO v_user_id FROM public.integration_recoveries
    WHERE id = p_recovery_id AND locked_by = p_worker_id AND locked_until > now();
    IF v_user_id IS NULL THEN RETURN -1; END IF;
    LOOP
        WITH batch AS (
            SELECT w.event_id FROM public.calendar_work_items w
            JOIN public.events e ON e.id = w.event_id
            WHERE e.user_id = v_user_id AND w.failure_code IN ('oauth_required', 'oauth_scope_required')
              AND w.status IN ('failed', 'blocked') AND e.recovery_id IS NULL
            ORDER BY w.event_id LIMIT p_batch_size FOR UPDATE OF w SKIP LOCKED
        )
        UPDATE public.events SET recovery_id = p_recovery_id
        WHERE id IN (SELECT event_id FROM batch);
        GET DIAGNOSTICS v_batch = ROW_COUNT;
        v_tagged := v_tagged + v_batch; v_batches := v_batches + 1;
        EXIT WHEN v_batch < p_batch_size OR v_batches >= p_max_batches;
    END LOOP;
    UPDATE public.integration_recoveries SET discovered_count = discovered_count + v_tagged,
        requeued_count = requeued_count + v_tagged, updated_at = now() WHERE id = p_recovery_id;
    UPDATE public.integration_recoveries SET status = 'waiting', remaining_count = (
        SELECT count(*) FROM public.calendar_work_items w JOIN public.events e ON e.id = w.event_id
        WHERE e.recovery_id = p_recovery_id AND w.status IN ('pending', 'processing', 'failed', 'blocked')
    ), locked_by = NULL, locked_until = NULL, updated_at = now() WHERE id = p_recovery_id;
    RETURN v_tagged;
END;
$$;

CREATE OR REPLACE FUNCTION public.refresh_waiting_calendar_recoveries(p_batch_size integer DEFAULT 20)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_id uuid; v_processed integer := 0; v_completed integer; v_remaining integer; v_errored integer;
BEGIN
    FOR v_id IN SELECT id FROM public.integration_recoveries WHERE status = 'waiting'
        ORDER BY updated_at LIMIT p_batch_size FOR UPDATE SKIP LOCKED LOOP
        SELECT count(*) FILTER (WHERE w.status = 'succeeded'),
               count(*) FILTER (WHERE w.status IN ('pending', 'processing')),
               count(*) FILTER (WHERE w.status IN ('failed', 'blocked'))
        INTO v_completed, v_remaining, v_errored
        FROM public.calendar_work_items w JOIN public.events e ON e.id = w.event_id
        WHERE e.recovery_id = v_id;
        IF v_remaining = 0 THEN
            UPDATE public.integration_recoveries SET status = CASE WHEN v_errored > 0 THEN 'completed_with_errors' ELSE 'completed' END,
                completed_count = v_completed, remaining_count = 0, completed_at = now(), updated_at = now() WHERE id = v_id;
        ELSE
            UPDATE public.integration_recoveries SET completed_count = v_completed, remaining_count = v_remaining, updated_at = now() WHERE id = v_id;
        END IF;
        v_processed := v_processed + 1;
    END LOOP;
    RETURN v_processed;
END;
$$;

REVOKE ALL ON FUNCTION public._enqueue_calendar_work(uuid, uuid, text, jsonb, text, boolean, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.set_event_review_status(uuid, text, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.complete_calendar_work(uuid, text, bigint, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.fail_calendar_work(uuid, text, bigint, text, text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.defer_calendar_work(uuid, text, bigint, timestamptz, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.apply_event_change_proposal(uuid, uuid, uuid, text, text, timestamptz, timestamptz, boolean, text, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.reject_event_change_proposal(uuid, uuid, uuid, text, boolean, text, text, timestamptz, timestamptz, boolean, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.reopen_event_change_proposal(uuid, uuid, uuid, text, text, jsonb, text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.ignore_sender_and_reject_pending(text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.undo_event_and_enqueue_calendar_work(uuid, uuid, text, jsonb, text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.unsync_event_and_enqueue_calendar_work(uuid, uuid, text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.queue_event_cancellation(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.commit_email_extraction(uuid, text, bigint, jsonb, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.unlock_expired_event_locks() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.requeue_calendar_recovery_batch(uuid, text, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.refresh_waiting_calendar_recoveries(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.set_event_review_status(uuid, text, uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION public.complete_calendar_work(uuid, text, bigint, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.fail_calendar_work(uuid, text, bigint, text, text, boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.defer_calendar_work(uuid, text, bigint, timestamptz, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.apply_event_change_proposal(uuid, uuid, uuid, text, text, timestamptz, timestamptz, boolean, text, text, text, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.reject_event_change_proposal(uuid, uuid, uuid, text, boolean, text, text, timestamptz, timestamptz, boolean, text, text, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.reopen_event_change_proposal(uuid, uuid, uuid, text, text, jsonb, text, boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.ignore_sender_and_reject_pending(text, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.undo_event_and_enqueue_calendar_work(uuid, uuid, text, jsonb, text, boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.unsync_event_and_enqueue_calendar_work(uuid, uuid, text, boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.queue_event_cancellation(uuid, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.commit_email_extraction(uuid, text, bigint, jsonb, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.unlock_expired_event_locks() TO service_role;
GRANT EXECUTE ON FUNCTION public.requeue_calendar_recovery_batch(uuid, text, integer, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.refresh_waiting_calendar_recoveries(integer) TO service_role;

COMMENT ON TABLE public.calendar_work_items IS 'V8 authoritative queue for worker-owned Google Calendar delivery';
