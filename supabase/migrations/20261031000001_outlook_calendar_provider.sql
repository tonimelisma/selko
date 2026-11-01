-- Outlook Calendar as a second calendar provider.
--
-- Until now every calendar write assumed Google: the claim joined
-- `integrations.provider = 'google_calendar'`, recovery existed only for
-- `google_calendar`, and the worker built a Google client unconditionally. An
-- Outlook user's approved events had nowhere to go.
--
-- Provider identity is carried by the ids themselves rather than by new
-- columns on events. Google ids stay bare (every existing row is one); an
-- Outlook id is stored qualified as `outlook:<graph id>`, both for calendar ids
-- (`user_calendar_settings.target_calendar_id`) and event ids
-- (`events.google_calendar_event_id`, `calendar_entries.provider_event_id`).
-- Neither Google event ids (base32hex) nor Google calendar ids (addresses)
-- can begin with that prefix. The consequence that matters: an id read back
-- from either provider, adopted by dedup and written through
-- commit_email_extraction, still says which calendar it lives in, so no
-- writer anywhere can attach an Outlook id to a Google write or the reverse.
-- `events.google_calendar_event_id` keeps its historical name; renaming it
-- would silently break every plpgsql body that references it, and none of
-- those bodies would notice until their first call.
--
-- The rule for where a write goes:
--   1. an event that already exists in a calendar stays in that calendar;
--   2. otherwise it goes to the provider of the user's target calendar;
--   3. with no target chosen, Google if connected, else a writable Outlook.
-- The provider is stamped on the work item at its first claim, so a retry
-- never changes calendars mid-flight even if the user switches targets.

-- 1. Which provider a work item writes to -------------------------------------

ALTER TABLE public.calendar_work_items
    ADD COLUMN IF NOT EXISTS provider text
    CHECK (provider IN ('google_calendar', 'outlook'));

COMMENT ON COLUMN public.calendar_work_items.provider IS
    'Calendar provider this item writes to, stamped at first claim. NULL until claimed.';

-- 2. Graph failures from calendar calls get their own surface -----------------

ALTER TABLE public.graph_api_failures
    DROP CONSTRAINT IF EXISTS graph_api_failures_graph_surface_check;
ALTER TABLE public.graph_api_failures
    ADD CONSTRAINT graph_api_failures_graph_surface_check
    CHECK (graph_surface IN ('outlook_mail', 'outlook_calendar', 'onedrive'));

-- 3. Provider resolution helpers ----------------------------------------------

CREATE OR REPLACE FUNCTION public.calendar_provider_of_id(p_id text)
RETURNS text LANGUAGE sql IMMUTABLE SET search_path = public AS $$
    SELECT CASE WHEN p_id LIKE 'outlook:%' THEN 'outlook' ELSE 'google_calendar' END;
$$;

-- A Microsoft consent is a set of scopes on the one Outlook row that also
-- carries mail. Outlook users who connected before calendar support hold a
-- mail-only grant; their row is active, and writing to their calendar would
-- fail on every call. Being active is therefore not enough for Outlook.
CREATE OR REPLACE FUNCTION public.outlook_scopes_allow_calendar(p_scopes text[])
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path = public AS $$
    SELECT EXISTS (
        SELECT 1 FROM unnest(COALESCE(p_scopes, '{}'::text[])) AS s
        WHERE lower(s) LIKE '%calendars.readwrite'
    );
$$;

CREATE OR REPLACE FUNCTION public.calendar_integration_writable(p_user_id uuid, p_provider text)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.integrations i
        WHERE i.user_id = p_user_id
          AND i.status = 'active'
          AND i.provider::text = p_provider
          AND (p_provider = 'google_calendar' OR public.outlook_scopes_allow_calendar(i.scopes))
    );
$$;

CREATE OR REPLACE FUNCTION public.calendar_write_provider(p_user_id uuid, p_event_id uuid)
RETURNS text LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
DECLARE v_existing text; v_target text;
BEGIN
    SELECT google_calendar_event_id INTO v_existing FROM public.events WHERE id = p_event_id;
    IF v_existing IS NOT NULL THEN
        RETURN public.calendar_provider_of_id(v_existing);
    END IF;
    SELECT target_calendar_id INTO v_target FROM public.user_calendar_settings WHERE user_id = p_user_id;
    IF v_target IS NOT NULL AND v_target <> '' THEN
        RETURN public.calendar_provider_of_id(v_target);
    END IF;
    IF public.calendar_integration_writable(p_user_id, 'google_calendar') THEN
        RETURN 'google_calendar';
    END IF;
    IF public.calendar_integration_writable(p_user_id, 'outlook') THEN
        RETURN 'outlook';
    END IF;
    RETURN 'google_calendar';
END;
$$;

REVOKE ALL ON FUNCTION public.calendar_integration_writable(uuid, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.calendar_write_provider(uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.calendar_provider_of_id(text) TO service_role;
GRANT EXECUTE ON FUNCTION public.outlook_scopes_allow_calendar(text[]) TO service_role;
GRANT EXECUTE ON FUNCTION public.calendar_integration_writable(uuid, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.calendar_write_provider(uuid, uuid) TO service_role;

-- 4. Claim: per-provider writability, per-provider circuit breaking ------------
--
-- p_providers lets the worker exclude a provider whose circuit is open without
-- starving the other one. NULL means every provider. The old two-argument form
-- is dropped rather than overloaded: a third defaulted argument would make a
-- two-argument call ambiguous.

DROP FUNCTION IF EXISTS public.claim_calendar_work_item(text, integer);

CREATE OR REPLACE FUNCTION public.claim_calendar_work_item(
    p_worker_id text, p_lease_seconds integer DEFAULT 300, p_providers text[] DEFAULT NULL
) RETURNS SETOF public.calendar_work_items
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_item public.calendar_work_items; v_provider text;
BEGIN
    SELECT w.* INTO v_item
    FROM public.calendar_work_items w
    CROSS JOIN LATERAL (
        SELECT COALESCE(w.provider, public.calendar_write_provider(w.user_id, w.event_id)) AS provider
    ) p
    WHERE w.status = 'pending'
      AND w.attempts < w.max_attempts
      AND (w.next_retry_at IS NULL OR w.next_retry_at <= now())
      AND (p_providers IS NULL OR p.provider = ANY(p_providers))
      AND public.calendar_integration_writable(w.user_id, p.provider)
    ORDER BY w.created_at ASC
    LIMIT 1
    FOR UPDATE OF w SKIP LOCKED;
    IF v_item.id IS NULL THEN
        SELECT w.* INTO v_item
        FROM public.calendar_work_items w
        CROSS JOIN LATERAL (
            SELECT COALESCE(w.provider, public.calendar_write_provider(w.user_id, w.event_id)) AS provider
        ) p
        WHERE w.status = 'processing'
          AND w.locked_until IS NOT NULL AND w.locked_until < now()
          AND w.attempts < w.max_attempts
          AND (p_providers IS NULL OR p.provider = ANY(p_providers))
          AND public.calendar_integration_writable(w.user_id, p.provider)
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
    v_provider := COALESCE(v_item.provider, public.calendar_write_provider(v_item.user_id, v_item.event_id));
    UPDATE public.calendar_work_items
    SET status = 'processing', locked_by = p_worker_id,
        locked_until = now() + make_interval(secs => greatest(p_lease_seconds, 1)),
        attempts = attempts + 1, provider = v_provider, updated_at = now()
    WHERE id = v_item.id
    RETURNING * INTO v_item;
    UPDATE public.events SET updated_at = now() WHERE id = v_item.event_id;
    RETURN NEXT v_item;
END;
$$;

REVOKE ALL ON FUNCTION public.claim_calendar_work_item(text, integer, text[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_calendar_work_item(text, integer, text[]) TO service_role;

-- 5. Recovery: per provider, and actually requeue -----------------------------
--
-- requeue_calendar_recovery_batch was named for requeuing but only tagged
-- events with recovery_id. fail_calendar_work parks an OAuth-blocked item as
-- 'blocked' (or 'failed' once its budget is spent), and the claim reads only
-- 'pending', so a parked item never ran again after the user reconnected: the
-- recovery card counted it as remaining until it went stale. It now returns
-- the item to 'pending' with one attempt of budget left, so the very next
-- claim delivers it. It also confines itself to the provider that was
-- reconnected -- reconnecting Outlook must not requeue items still blocked on
-- an expired Google grant.

CREATE OR REPLACE FUNCTION public.requeue_calendar_recovery_batch(
    p_recovery_id uuid, p_worker_id text, p_batch_size integer DEFAULT 100,
    p_max_batches integer DEFAULT 5
) RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_user_id uuid; v_provider text; v_tagged integer := 0; v_batch integer; v_batches integer := 0;
BEGIN
    SELECT user_id, provider::text INTO v_user_id, v_provider FROM public.integration_recoveries
    WHERE id = p_recovery_id AND locked_by = p_worker_id AND locked_until > now();
    IF v_user_id IS NULL THEN RETURN -1; END IF;
    LOOP
        WITH batch AS (
            SELECT w.id AS item_id, w.event_id FROM public.calendar_work_items w
            JOIN public.events e ON e.id = w.event_id
            WHERE e.user_id = v_user_id AND w.failure_code IN ('oauth_required', 'oauth_scope_required')
              AND w.status IN ('failed', 'blocked') AND e.recovery_id IS NULL
              AND COALESCE(w.provider, public.calendar_write_provider(w.user_id, w.event_id)) = v_provider
              -- A newer item for the same event supersedes this one; the
              -- one-active-per-event index forbids reviving both.
              AND NOT EXISTS (
                  SELECT 1 FROM public.calendar_work_items newer
                  WHERE newer.event_id = w.event_id AND newer.status IN ('pending', 'processing')
              )
            ORDER BY w.event_id LIMIT p_batch_size FOR UPDATE OF w SKIP LOCKED
        ), revived AS (
            UPDATE public.calendar_work_items w
            SET status = 'pending', locked_by = NULL, locked_until = NULL,
                next_retry_at = NULL, completed_at = NULL,
                attempts = least(w.attempts, w.max_attempts - 1), updated_at = now()
            FROM batch WHERE w.id = batch.item_id
            RETURNING w.event_id
        )
        UPDATE public.events SET recovery_id = p_recovery_id, updated_at = now()
        WHERE id IN (SELECT event_id FROM revived);
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

REVOKE ALL ON FUNCTION public.requeue_calendar_recovery_batch(uuid, text, integer, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.requeue_calendar_recovery_batch(uuid, text, integer, integer) TO service_role;

-- Reconnecting Outlook with a calendar grant opens a recovery generation just
-- as reconnecting Google Calendar does. A mail-only Outlook consent does not:
-- it cannot unblock any calendar write, so a recovery card would only lie.
CREATE OR REPLACE FUNCTION public.complete_integration_reauthorization(
    p_user_id uuid,
    p_provider text,
    p_access_token text,
    p_refresh_token text DEFAULT NULL,
    p_token_expiry timestamptz DEFAULT NULL,
    p_scopes text[] DEFAULT '{}'::text[],
    p_provider_email text DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_integration_id uuid;
BEGIN
    INSERT INTO public.integrations (
        user_id, provider, status, access_token, refresh_token,
        token_expiry, scopes, provider_email
    ) VALUES (
        p_user_id, p_provider::integration_provider, 'active', p_access_token,
        p_refresh_token, p_token_expiry, COALESCE(p_scopes, '{}'), p_provider_email
    )
    ON CONFLICT (user_id, provider) DO UPDATE SET
        status = 'active',
        access_token = EXCLUDED.access_token,
        -- Google/Microsoft omit the refresh token on a subsequent consent
        -- screen; never overwrite a working one with NULL.
        refresh_token = COALESCE(EXCLUDED.refresh_token, public.integrations.refresh_token),
        token_expiry = EXCLUDED.token_expiry,
        scopes = EXCLUDED.scopes,
        provider_email = COALESCE(EXCLUDED.provider_email, public.integrations.provider_email),
        updated_at = now()
    RETURNING id INTO v_integration_id;

    IF p_provider = 'google_calendar'
       OR (p_provider = 'outlook' AND public.outlook_scopes_allow_calendar(p_scopes)) THEN
        UPDATE public.integration_recoveries
        SET status = 'superseded',
            -- The lease dies with the generation.
            locked_by = NULL,
            locked_until = NULL,
            updated_at = now()
        WHERE integration_id = v_integration_id
          AND status IN ('pending', 'processing', 'waiting');

        INSERT INTO public.integration_recoveries (
            integration_id, user_id, provider, reason, status
        ) VALUES (
            v_integration_id, p_user_id, p_provider::integration_provider,
            'reauthorization', 'pending'
        );
    END IF;

    RETURN v_integration_id;
END;
$$;

REVOKE ALL ON FUNCTION public.complete_integration_reauthorization(uuid, text, text, text, timestamptz, text[], text)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.complete_integration_reauthorization(uuid, text, text, text, timestamptz, text[], text)
    TO service_role;
