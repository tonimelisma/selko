-- W1: revoke SECURITY DEFINER execution from the roles PostgREST authenticates as.
--
-- Supabase installs, at project creation:
--     ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS
--         TO anon, authenticated, service_role;
--
-- so every function created in public receives a DIRECT grant to anon and
-- authenticated. Every `REVOKE ALL ON FUNCTION ... FROM PUBLIC` in this
-- repository -- including the sixteen in 20260829000001 and the whole of
-- 20260811000005 -- revokes the PUBLIC pseudo-role and leaves the direct grant
-- untouched. Measured 2026-08-21: 56/56 SECURITY DEFINER functions in staging
-- and 45/45 in production were executable by anon, whose key ships in every
-- client build. The exposed set included commit_email_extraction,
-- save_email_with_attachment_descriptors, claim_unprocessed_email and
-- get_llm_usage_summary(p_user_id, ...).
--
-- This migration closes it in three parts: the default so new functions are
-- private on creation, the existing functions, and an explicit re-grant of the
-- four RPCs a signed-in user is actually meant to call. The contract set is
-- pinned in tests/integration/test_schema_contract.py.

-- 1. Close the default. Only the grantor that owns the functions matters; a
--    migration runs as the owner, so its default is the one that applies.
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM anon;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM authenticated;

-- 2. Revoke every existing direct grant. Enumerating names would rot on the
--    next DROP+CREATE; the catalog is the source of truth. service_role is
--    untouched -- it is the worker identity and every claim/heartbeat/complete
--    RPC depends on it.
DO $$
DECLARE
    v_function record;
BEGIN
    FOR v_function IN
        SELECT p.oid::regprocedure AS signature
        FROM pg_proc AS p
        JOIN pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.prosecdef
    LOOP
        -- PUBLIC as well as the two API roles. PostgreSQL's own default is
        -- GRANT EXECUTE ... TO PUBLIC, and anon inherits through it, so a
        -- function created without an explicit revoke is reachable even when
        -- the Supabase default ACL is closed. 20260829000001 created three
        -- broadcast trigger functions that way; executing this migration
        -- against the local database is what surfaced them.
        EXECUTE format(
            'REVOKE ALL ON FUNCTION %s FROM PUBLIC, anon, authenticated',
            v_function.signature
        );
    END LOOP;
END;
$$;

-- 3. set_event_review_status gated on `auth.uid() IS NOT NULL`, so a caller
--    with a NULL uid skipped the ownership check entirely and COALESCE fell
--    back to the caller-supplied p_user_id. Step 2 removes the anon path that
--    made that reachable; this makes the function correct on its own terms,
--    using the same guard reprocess_email already uses.
CREATE OR REPLACE FUNCTION public.set_event_review_status(
    p_event_id uuid, p_review_status text, p_user_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_event public.events;
    v_item public.calendar_work_items;
    v_user_id uuid;
BEGIN
    IF p_review_status NOT IN ('active', 'rejected') THEN
        RAISE EXCEPTION 'invalid event review status %', p_review_status USING ERRCODE = '22023';
    END IF;
    IF p_user_id IS NOT NULL
       AND auth.uid() IS DISTINCT FROM p_user_id
       AND auth.role() <> 'service_role' THEN
        RAISE EXCEPTION 'event % is not owned by the caller', p_event_id USING ERRCODE = '42501';
    END IF;
    v_user_id := COALESCE(p_user_id, auth.uid());
    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'authentication required' USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_event FROM public.events
    WHERE id = p_event_id AND user_id = v_user_id FOR UPDATE;
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

-- 4. Re-grant exactly the contract set. Each of these derives the acting user
--    from auth.uid(), or rejects a p_user_id that is not auth.uid().
REVOKE ALL ON FUNCTION public.set_event_review_status(uuid, text, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.set_event_review_status(uuid, text, uuid) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.reprocess_email(uuid, uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION public.request_email_sync_now(uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION public.set_email_folder_preference(uuid, boolean) TO authenticated;

COMMENT ON FUNCTION public.set_event_review_status(uuid, text, uuid) IS
    'Owns the user review decision. Rejects a p_user_id that is not auth.uid() unless the caller is service_role.';
