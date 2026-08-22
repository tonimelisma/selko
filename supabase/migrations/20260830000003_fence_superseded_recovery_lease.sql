-- Clear the worker lease when a recovery generation is superseded.
--
-- complete_integration_reauthorization marked the previous generation
-- `superseded` but left `locked_by` and `locked_until` untouched. Every worker
-- RPC fences on `locked_by = p_worker_id AND locked_until > now()` and none of
-- them re-check `status`, so a worker holding a superseded generation still
-- passed the fence and could act on it. requeue_calendar_recovery_batch then
-- ran to completion and tried to set the superseded row to 'waiting',
-- colliding with the replacement row on
-- integration_recoveries_one_active_idx:
--
--   duplicate key value violates unique constraint
--   "integration_recoveries_one_active_idx"
--
-- test_superseded_recovery_cannot_be_requeued_by_old_worker is named for
-- exactly this property and has been failing on main.
--
-- Superseding is a fencing event, so it must revoke the lease that fencing is
-- built on. With the lease cleared the old worker's SELECT finds no row and
-- the RPC returns -1, which is what the test asserts.
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

    IF p_provider = 'google_calendar' THEN
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
