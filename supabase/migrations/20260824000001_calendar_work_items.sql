-- S2: make calendar delivery a first-class, worker-owned queue.
--
-- The legacy events.status queue remains as a compatibility projection during
-- S2-S4. calendar_work_items is the authority for delivery ownership,
-- retries, and provider-write fencing.

CREATE TABLE IF NOT EXISTS public.calendar_work_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id uuid NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    action text NOT NULL CHECK (action IN ('upsert', 'cancel')),
    generation bigint NOT NULL CHECK (generation > 0),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'succeeded', 'failed', 'blocked', 'superseded')),
    desired_event jsonb,
    provider_event_id text,
    expected_provider_revision text,
    force_overwrite boolean NOT NULL DEFAULT false,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    locked_by text,
    locked_until timestamptz,
    next_retry_at timestamptz,
    failure_code text,
    failure_detail text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

ALTER TABLE public.calendar_work_items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users can read own calendar work" ON public.calendar_work_items;
CREATE POLICY "Users can read own calendar work"
    ON public.calendar_work_items FOR SELECT
    USING (auth.uid() = user_id);

REVOKE ALL ON TABLE public.calendar_work_items FROM anon;
REVOKE ALL ON TABLE public.calendar_work_items FROM authenticated;
GRANT SELECT ON TABLE public.calendar_work_items TO authenticated;
REVOKE ALL ON TABLE public.calendar_work_items FROM PUBLIC;
GRANT ALL ON TABLE public.calendar_work_items TO service_role;

CREATE UNIQUE INDEX IF NOT EXISTS calendar_work_items_one_active_per_event
    ON public.calendar_work_items(event_id)
    WHERE status IN ('pending', 'processing');
CREATE INDEX IF NOT EXISTS calendar_work_items_claim_idx
    ON public.calendar_work_items(status, next_retry_at, created_at)
    WHERE status IN ('pending', 'processing');
CREATE INDEX IF NOT EXISTS calendar_work_items_user_idx
    ON public.calendar_work_items(user_id, created_at DESC);

ALTER TABLE public.events
    ADD COLUMN IF NOT EXISTS review_status text NOT NULL DEFAULT 'pending_review';

ALTER TABLE public.events DROP CONSTRAINT IF EXISTS events_review_status_check;
ALTER TABLE public.events ADD CONSTRAINT events_review_status_check
    CHECK (review_status IN ('pending_review', 'active', 'rejected', 'cancelled'));

UPDATE public.events
SET review_status = CASE status
    WHEN 'pending_review' THEN 'pending_review'
    WHEN 'rejected' THEN 'rejected'
    WHEN 'cancelled' THEN 'cancelled'
    ELSE 'active'
END;

CREATE OR REPLACE FUNCTION public.calendar_work_item_owner_check()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_owner uuid;
BEGIN
    SELECT user_id INTO v_owner FROM public.events WHERE id = NEW.event_id;
    IF v_owner IS NULL OR v_owner <> NEW.user_id THEN
        RAISE EXCEPTION 'calendar work item owner does not match event owner'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.calendar_work_item_owner_check() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.calendar_work_item_owner_check() TO service_role;
DROP TRIGGER IF EXISTS calendar_work_items_owner_check ON public.calendar_work_items;
CREATE TRIGGER calendar_work_items_owner_check
    BEFORE INSERT OR UPDATE ON public.calendar_work_items
    FOR EACH ROW EXECUTE FUNCTION public.calendar_work_item_owner_check();

-- Backfill work for rows that were already waiting in the event queue. A
-- syncing row is preserved as processing with its existing lease so deploying
-- this migration cannot cause a duplicate provider write.
UPDATE public.events
SET calendar_work_generation = GREATEST(calendar_work_generation, 1)
WHERE status IN ('approved', 'cancel_queued', 'syncing');

INSERT INTO public.calendar_work_items (
    event_id, user_id, action, generation, status, desired_event,
    provider_event_id, attempts, max_attempts, locked_by, locked_until,
    next_retry_at, created_at, updated_at
)
SELECT
    e.id,
    e.user_id,
    e.calendar_sync_action,
    e.calendar_work_generation,
    CASE WHEN e.status = 'syncing' THEN 'processing' ELSE 'pending' END,
    jsonb_build_object(
        'title', e.title, 'start_datetime', e.start_datetime,
        'end_datetime', e.end_datetime, 'all_day', e.all_day,
        'location', e.location, 'description', e.description,
        'importance', e.importance, 'source_attribution', e.source_attribution
    ),
    e.google_calendar_event_id,
    e.sync_attempts,
    e.max_sync_attempts,
    e.locked_by,
    e.locked_until,
    e.next_retry_at,
    e.updated_at,
    e.updated_at
FROM public.events e
WHERE e.status IN ('approved', 'cancel_queued', 'syncing')
  AND NOT EXISTS (
      SELECT 1 FROM public.calendar_work_items w
      WHERE w.event_id = e.id AND w.status IN ('pending', 'processing')
  );

CREATE OR REPLACE FUNCTION public._enqueue_calendar_work(
    p_event_id uuid,
    p_user_id uuid,
    p_action text,
    p_desired_event jsonb,
    p_expected_provider_revision text,
    p_force_overwrite boolean,
    p_legacy_status text
) RETURNS public.calendar_work_items
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_event public.events;
    v_item public.calendar_work_items;
    v_generation bigint;
BEGIN
    IF p_action NOT IN ('upsert', 'cancel') THEN
        RAISE EXCEPTION 'invalid calendar work action %', p_action USING ERRCODE = '22023';
    END IF;
    IF p_action = 'upsert' AND p_desired_event IS NULL THEN
        RAISE EXCEPTION 'upsert calendar work requires desired_event' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_event
    FROM public.events
    WHERE id = p_event_id AND user_id = p_user_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'event % is not owned by user %', p_event_id, p_user_id
            USING ERRCODE = '42501';
    END IF;

    v_generation := GREATEST(v_event.calendar_work_generation, 0) + 1;

    UPDATE public.calendar_work_items
    SET status = 'superseded', updated_at = now(), completed_at = now()
    WHERE event_id = p_event_id AND status IN ('pending', 'processing');

    PERFORM set_config('selko.calendar_work_rpc', '1', true);
    UPDATE public.events
    SET status = COALESCE(p_legacy_status,
                          CASE WHEN p_action = 'cancel' THEN 'cancel_queued' ELSE 'approved' END),
        review_status = CASE
            WHEN status IN ('pending_review', 'rejected', 'cancelled') THEN 'active'
            ELSE review_status
        END,
        calendar_sync_action = p_action,
        calendar_work_generation = v_generation,
        sync_attempts = 0,
        sync_error = NULL,
        sync_failure_code = NULL,
        dead_letter_reason = NULL,
        dead_letter_at = NULL,
        locked_by = NULL,
        locked_until = NULL,
        next_retry_at = NULL,
        updated_at = now()
    WHERE id = p_event_id;

    INSERT INTO public.calendar_work_items (
        event_id, user_id, action, generation, desired_event,
        provider_event_id, expected_provider_revision, force_overwrite,
        attempts, max_attempts
    ) VALUES (
        p_event_id, p_user_id, p_action, v_generation,
        p_desired_event,
        v_event.google_calendar_event_id, p_expected_provider_revision,
        COALESCE(p_force_overwrite, false), v_event.max_sync_attempts,
        v_event.max_sync_attempts
    ) RETURNING * INTO v_item;

    RETURN v_item;
END;
$$;

CREATE OR REPLACE FUNCTION public.enqueue_calendar_work(
    p_event_id uuid,
    p_user_id uuid,
    p_action text,
    p_desired_event jsonb DEFAULT NULL,
    p_expected_provider_revision text DEFAULT NULL,
    p_force_overwrite boolean DEFAULT false
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_item public.calendar_work_items;
BEGIN
    v_item := public._enqueue_calendar_work(
        p_event_id, p_user_id, p_action, p_desired_event,
        p_expected_provider_revision, p_force_overwrite, NULL
    );
    RETURN jsonb_build_object(
        'id', v_item.id, 'event_id', v_item.event_id,
        'generation', v_item.generation, 'status', v_item.status,
        'action', v_item.action
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.claim_calendar_work_item(
    p_worker_id text,
    p_lease_seconds integer DEFAULT 300
) RETURNS SETOF public.calendar_work_items
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_item public.calendar_work_items;
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

    PERFORM set_config('selko.calendar_work_rpc', '1', true);
    UPDATE public.events
    SET status = 'syncing', locked_by = p_worker_id,
        locked_until = v_item.locked_until, sync_attempts = v_item.attempts,
        calendar_sync_action = v_item.action, updated_at = now()
    WHERE id = v_item.event_id AND calendar_work_generation = v_item.generation;

    RETURN NEXT v_item;
END;
$$;

CREATE OR REPLACE FUNCTION public.claim_calendar_work(
    p_worker_id text,
    p_lease_seconds integer DEFAULT 300
) RETURNS SETOF public.events
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_item public.calendar_work_items;
BEGIN
    SELECT * INTO v_item FROM public.claim_calendar_work_item(p_worker_id, p_lease_seconds);
    IF v_item.id IS NOT NULL THEN
        RETURN QUERY SELECT * FROM public.events WHERE id = v_item.event_id;
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.heartbeat_calendar_work(
    p_item_id uuid, p_worker_id text, p_generation bigint, p_lease_seconds integer
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_updated integer;
BEGIN
    UPDATE public.calendar_work_items
    SET locked_until = now() + make_interval(secs => greatest(p_lease_seconds, 1)), updated_at = now()
    WHERE id = p_item_id AND generation = p_generation AND status = 'processing'
      AND locked_by = p_worker_id AND locked_until > now();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated = 1 THEN
        UPDATE public.events e
        SET locked_until = now() + make_interval(secs => greatest(p_lease_seconds, 1)), updated_at = now()
        FROM public.calendar_work_items w
        WHERE w.id = p_item_id AND e.id = w.event_id
          AND e.locked_by = p_worker_id AND e.calendar_work_generation = p_generation;
    END IF;
    RETURN v_updated = 1;
END;
$$;

CREATE OR REPLACE FUNCTION public.complete_calendar_work(
    p_item_id uuid,
    p_worker_id text,
    p_generation bigint,
    p_provider_event_id text,
    p_provider_revision text DEFAULT NULL
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_item public.calendar_work_items; v_updated integer;
BEGIN
    SELECT * INTO v_item FROM public.calendar_work_items
    WHERE id = p_item_id FOR UPDATE;
    IF NOT FOUND OR v_item.status <> 'processing'
       OR v_item.locked_by IS DISTINCT FROM p_worker_id
       OR v_item.generation IS DISTINCT FROM p_generation THEN
        RETURN false;
    END IF;

    PERFORM set_config('selko.calendar_work_rpc', '1', true);
    UPDATE public.events
    SET status = CASE
            WHEN v_item.action = 'cancel'
                AND COALESCE((v_item.desired_event->>'delete_remote')::boolean, false)
                THEN 'pending_review'
            WHEN v_item.action = 'cancel' THEN 'cancelled'
            ELSE 'synced'
        END,
        review_status = CASE
            WHEN v_item.action = 'cancel'
                AND COALESCE((v_item.desired_event->>'delete_remote')::boolean, false)
                THEN 'pending_review'
            WHEN v_item.action = 'cancel' THEN 'cancelled'
            ELSE review_status
        END,
        google_calendar_event_id = CASE
            WHEN v_item.action = 'cancel'
                AND COALESCE((v_item.desired_event->>'delete_remote')::boolean, false)
                THEN NULL
            ELSE COALESCE(p_provider_event_id, google_calendar_event_id)
        END,
        synced_at = CASE
            WHEN v_item.action = 'cancel'
                AND COALESCE((v_item.desired_event->>'delete_remote')::boolean, false)
                THEN NULL
            ELSE now()
        END,
        sync_error = NULL, sync_failure_code = NULL,
        locked_by = NULL, locked_until = NULL, next_retry_at = NULL, updated_at = now()
    WHERE id = v_item.event_id AND status = 'syncing'
      AND locked_by = p_worker_id AND calendar_work_generation = p_generation;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 1 THEN
        RETURN false;
    END IF;

    UPDATE public.calendar_work_items
    SET status = 'succeeded', provider_event_id = COALESCE(p_provider_event_id, provider_event_id),
        expected_provider_revision = COALESCE(p_provider_revision, expected_provider_revision),
        locked_by = NULL, locked_until = NULL, updated_at = now(), completed_at = now()
    WHERE id = p_item_id;
    RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION public.fail_calendar_work(
    p_item_id uuid,
    p_worker_id text,
    p_generation bigint,
    p_error_code text,
    p_error_detail text DEFAULT NULL,
    p_retryable boolean DEFAULT true
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_item public.calendar_work_items; v_status text; v_event_status text;
BEGIN
    SELECT * INTO v_item FROM public.calendar_work_items
    WHERE id = p_item_id FOR UPDATE;
    IF NOT FOUND OR v_item.status <> 'processing'
       OR v_item.locked_by IS DISTINCT FROM p_worker_id
       OR v_item.generation IS DISTINCT FROM p_generation THEN
        RETURN jsonb_build_object('fenced', true);
    END IF;

    IF p_retryable AND v_item.attempts < v_item.max_attempts THEN
        v_status := 'pending';
        v_event_status := CASE WHEN v_item.action = 'cancel' THEN 'cancel_queued' ELSE 'approved' END;
        UPDATE public.calendar_work_items
        SET status = 'pending', failure_code = left(p_error_code, 100),
            failure_detail = left(p_error_detail, 500),
            locked_by = NULL, locked_until = NULL,
            next_retry_at = now() + make_interval(secs => least(1800, greatest(60, 60 * power(2, least(attempts - 1, 5))::integer))),
            updated_at = now()
        WHERE id = p_item_id;
    ELSE
        v_status := CASE WHEN p_retryable THEN 'failed' ELSE 'blocked' END;
        -- OAuth is a capability pause, not a terminal delivery failure. Keep
        -- the legacy projection claimable after reconnect while the item is
        -- marked blocked for the recovery workflow to requeue explicitly.
        v_event_status := CASE
            WHEN p_error_code IN ('oauth_required', 'oauth_scope_required')
                THEN CASE WHEN v_item.action = 'cancel' THEN 'cancel_queued' ELSE 'approved' END
            ELSE 'sync_failed'
        END;
        UPDATE public.calendar_work_items
        SET status = v_status, failure_code = left(p_error_code, 100),
            failure_detail = left(p_error_detail, 500),
            locked_by = NULL, locked_until = NULL, completed_at = now(), updated_at = now()
        WHERE id = p_item_id;
    END IF;

    PERFORM set_config('selko.calendar_work_rpc', '1', true);
    UPDATE public.events
    SET status = v_event_status, sync_error = left(COALESCE(p_error_detail, p_error_code), 500),
        sync_failure_code = left(p_error_code, 100), locked_by = NULL, locked_until = NULL,
        next_retry_at = CASE WHEN v_status = 'pending' THEN now() + interval '60 seconds' ELSE NULL END,
        dead_letter_reason = CASE WHEN v_status IN ('failed', 'blocked') THEN left(p_error_code, 100) ELSE NULL END,
        dead_letter_at = CASE WHEN v_status IN ('failed', 'blocked') THEN now() ELSE NULL END,
        updated_at = now()
    WHERE id = v_item.event_id AND status = 'syncing'
      AND locked_by = p_worker_id AND calendar_work_generation = p_generation;

    RETURN jsonb_build_object('fenced', false, 'status', v_status, 'event_status', v_event_status);
END;
$$;

CREATE OR REPLACE FUNCTION public.defer_calendar_work(
    p_item_id uuid,
    p_worker_id text,
    p_generation bigint,
    p_next_retry_at timestamptz,
    p_detail text DEFAULT 'calendar quota exceeded'
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_item public.calendar_work_items; v_updated integer;
BEGIN
    SELECT * INTO v_item FROM public.calendar_work_items
    WHERE id = p_item_id FOR UPDATE;
    IF NOT FOUND OR v_item.status <> 'processing'
       OR v_item.locked_by IS DISTINCT FROM p_worker_id
       OR v_item.generation IS DISTINCT FROM p_generation THEN
        RETURN false;
    END IF;

    UPDATE public.calendar_work_items
    SET status = 'pending', attempts = greatest(attempts - 1, 0),
        failure_code = 'calendar_quota', failure_detail = left(p_detail, 500),
        locked_by = NULL, locked_until = NULL, next_retry_at = p_next_retry_at,
        updated_at = now()
    WHERE id = p_item_id;
    PERFORM set_config('selko.calendar_work_rpc', '1', true);
    UPDATE public.events
    SET status = CASE WHEN v_item.action = 'cancel' THEN 'cancel_queued' ELSE 'approved' END,
        sync_attempts = greatest(sync_attempts - 1, 0), sync_error = left(p_detail, 500),
        locked_by = NULL, locked_until = NULL, next_retry_at = p_next_retry_at, updated_at = now()
    WHERE id = v_item.event_id AND status = 'syncing'
      AND locked_by = p_worker_id AND calendar_work_generation = p_generation;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END;
$$;

CREATE OR REPLACE FUNCTION public.undo_event_and_enqueue_calendar_work(
    p_event_id uuid,
    p_user_id uuid,
    p_change_source_id uuid DEFAULT NULL,
    p_restore_fields jsonb DEFAULT '{}'::jsonb,
    p_action text DEFAULT NULL,
    p_desired_event jsonb DEFAULT NULL,
    p_expected_provider_revision text DEFAULT NULL,
    p_force_overwrite boolean DEFAULT false
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_event public.events; v_item public.calendar_work_items; v_status text;
BEGIN
    SELECT * INTO v_event FROM public.events
    WHERE id = p_event_id AND user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'event % is not owned by user %', p_event_id, p_user_id
            USING ERRCODE = '42501';
    END IF;
    IF p_action IS NOT NULL AND p_action NOT IN ('upsert', 'cancel') THEN
        RAISE EXCEPTION 'invalid undo calendar action %', p_action USING ERRCODE = '22023';
    END IF;

    IF p_action IS NOT NULL THEN
        v_item := public._enqueue_calendar_work(
            p_event_id, p_user_id, p_action, p_desired_event,
            p_expected_provider_revision, p_force_overwrite,
            CASE WHEN p_action = 'cancel' THEN 'cancel_queued' ELSE 'approved' END
        );
    END IF;

    PERFORM set_config('selko.calendar_work_rpc', '1', true);
    IF p_change_source_id IS NOT NULL THEN
        v_status := 'pending_change';
        UPDATE public.events
        SET title = COALESCE(p_restore_fields->>'title', title),
            start_datetime = CASE WHEN p_restore_fields ? 'start_datetime'
                THEN NULLIF(p_restore_fields->>'start_datetime', '')::timestamptz ELSE start_datetime END,
            end_datetime = CASE WHEN p_restore_fields ? 'end_datetime'
                THEN NULLIF(p_restore_fields->>'end_datetime', '')::timestamptz ELSE end_datetime END,
            all_day = COALESCE((p_restore_fields->>'all_day')::boolean, all_day),
            location = CASE WHEN p_restore_fields ? 'location' THEN p_restore_fields->>'location' ELSE location END,
            description = CASE WHEN p_restore_fields ? 'description' THEN p_restore_fields->>'description' ELSE description END,
            importance = COALESCE(p_restore_fields->>'importance', importance),
            google_calendar_event_id = CASE WHEN p_restore_fields ? 'google_calendar_event_id'
                THEN p_restore_fields->>'google_calendar_event_id' ELSE google_calendar_event_id END,
            synced_at = CASE WHEN p_restore_fields ? 'synced_at'
                THEN NULLIF(p_restore_fields->>'synced_at', '')::timestamptz ELSE synced_at END,
            status = v_status, review_status = 'active', updated_at = now()
        WHERE id = p_event_id;
    ELSIF p_action = 'cancel' THEN
        -- The cancellation work remains queued until the worker completes;
        -- review_status already records that Undo returned the event to New.
        UPDATE public.events
        SET status = 'cancel_queued', review_status = 'pending_review', updated_at = now()
        WHERE id = p_event_id;
        v_status := 'pending_review';
    ELSE
        UPDATE public.events
        SET status = 'pending_review', review_status = 'pending_review', updated_at = now()
        WHERE id = p_event_id;
        v_status := 'pending_review';
    END IF;

    RETURN jsonb_build_object(
        'status', v_status,
        'work_item_id', CASE WHEN v_item.id IS NULL THEN NULL ELSE v_item.id END,
        'generation', CASE WHEN v_item.id IS NULL THEN NULL ELSE v_item.generation END
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.unsync_event_and_enqueue_calendar_work(
    p_event_id uuid,
    p_user_id uuid,
    p_expected_provider_revision text DEFAULT NULL,
    p_force_overwrite boolean DEFAULT false
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_event public.events; v_item public.calendar_work_items;
BEGIN
    SELECT * INTO v_event FROM public.events
    WHERE id = p_event_id AND user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'event % is not owned by user %', p_event_id, p_user_id
            USING ERRCODE = '42501';
    END IF;
    IF v_event.status <> 'synced' OR v_event.google_calendar_event_id IS NULL THEN
        RAISE EXCEPTION 'event % is not synced', p_event_id USING ERRCODE = '22023';
    END IF;

    v_item := public._enqueue_calendar_work(
        p_event_id, p_user_id, 'cancel',
        '{"delete_remote": true}'::jsonb,
        p_expected_provider_revision, p_force_overwrite, 'cancel_queued'
    );

    PERFORM set_config('selko.calendar_work_rpc', '1', true);
    UPDATE public.events
    SET review_status = 'pending_review', updated_at = now()
    WHERE id = p_event_id;

    RETURN jsonb_build_object(
        'status', 'pending_review', 'work_item_id', v_item.id,
        'generation', v_item.generation
    );
END;
$$;

-- Compatibility transition for old clients that still approve directly by
-- updating events.status. The RPC sets this GUC while it performs its own
-- projection, so the trigger cannot recurse or create a second work item.
CREATE OR REPLACE FUNCTION public.events_legacy_calendar_enqueue_compat()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_transition boolean;
BEGIN
    IF current_setting('selko.calendar_work_rpc', true) = '1' THEN RETURN NEW; END IF;
    v_transition := TG_OP = 'INSERT';
    IF TG_OP = 'UPDATE' THEN
        v_transition := OLD.status IS DISTINCT FROM NEW.status
            OR OLD.calendar_sync_action IS DISTINCT FROM NEW.calendar_sync_action;
    END IF;
    IF NEW.status IN ('approved', 'cancel_queued')
       AND v_transition
       AND NOT EXISTS (
           SELECT 1 FROM public.calendar_work_items w
           WHERE w.event_id = NEW.id AND w.status IN ('pending', 'processing')
       ) THEN
        PERFORM public.enqueue_calendar_work(
            NEW.id, NEW.user_id, CASE WHEN NEW.status = 'cancel_queued' THEN 'cancel' ELSE 'upsert' END,
            CASE WHEN NEW.status = 'cancel_queued' THEN NULL ELSE jsonb_build_object(
                'title', NEW.title, 'start_datetime', NEW.start_datetime,
                'end_datetime', NEW.end_datetime, 'all_day', NEW.all_day,
                'location', NEW.location, 'description', NEW.description,
                'importance', NEW.importance, 'source_attribution', NEW.source_attribution
            ) END,
            NULL, false
        );
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.events_legacy_calendar_enqueue_compat() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.events_legacy_calendar_enqueue_compat() TO service_role;
DROP TRIGGER IF EXISTS events_legacy_calendar_enqueue_compat ON public.events;
CREATE TRIGGER events_legacy_calendar_enqueue_compat
    AFTER INSERT OR UPDATE OF status, calendar_sync_action ON public.events
    FOR EACH ROW EXECUTE FUNCTION public.events_legacy_calendar_enqueue_compat();

CREATE OR REPLACE FUNCTION public.events_review_status_compat()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    NEW.review_status := CASE NEW.status
        WHEN 'pending_review' THEN 'pending_review'
        WHEN 'rejected' THEN 'rejected'
        WHEN 'cancelled' THEN 'cancelled'
        ELSE 'active'
    END;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.events_review_status_compat() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.events_review_status_compat() TO service_role;
DROP TRIGGER IF EXISTS events_review_status_compat ON public.events;
CREATE TRIGGER events_review_status_compat
    BEFORE INSERT OR UPDATE OF status ON public.events
    FOR EACH ROW EXECUTE FUNCTION public.events_review_status_compat();

REVOKE ALL ON FUNCTION public._enqueue_calendar_work(uuid, uuid, text, jsonb, text, boolean, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.enqueue_calendar_work(uuid, uuid, text, jsonb, text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_calendar_work_item(text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_calendar_work(text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.heartbeat_calendar_work(uuid, text, bigint, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.complete_calendar_work(uuid, text, bigint, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.fail_calendar_work(uuid, text, bigint, text, text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.defer_calendar_work(uuid, text, bigint, timestamptz, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.undo_event_and_enqueue_calendar_work(uuid, uuid, uuid, jsonb, text, jsonb, text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.unsync_event_and_enqueue_calendar_work(uuid, uuid, text, boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.enqueue_calendar_work(uuid, uuid, text, jsonb, text, boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_calendar_work_item(text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_calendar_work(text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.heartbeat_calendar_work(uuid, text, bigint, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.complete_calendar_work(uuid, text, bigint, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.fail_calendar_work(uuid, text, bigint, text, text, boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.defer_calendar_work(uuid, text, bigint, timestamptz, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.undo_event_and_enqueue_calendar_work(uuid, uuid, uuid, jsonb, text, jsonb, text, boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.unsync_event_and_enqueue_calendar_work(uuid, uuid, text, boolean) TO service_role;

COMMENT ON TABLE public.calendar_work_items IS 'S2 authoritative queue for worker-owned Google Calendar delivery';
COMMENT ON FUNCTION public.claim_calendar_work_item(text, integer) IS 'Claims one calendar work item with an owner and generation fence';
