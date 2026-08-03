-- Recovery claim self-heal (review fix for oauth-reconnect-catch-up.md section 2)
--
-- claim_integration_recovery originally claimed only status='pending' rows.
-- A worker that crashed mid-claim left the recovery 'processing' with an
-- expired lock, and because unlock_expired_integration_recoveries only runs
-- on API startup, the generation stayed wedged until the next restart.
-- Every other claim in the system (events, emails, photos, scheduled tasks)
-- already reclaims rows whose lock has expired; align this one with them so
-- a crashed claim is picked back up on the next poll instead of waiting for
-- a restart.

-- 20260802000004 shipped RLS policies but forgot the Data API table grants.
-- As documented in 20260801000001, RLS is the row-level authorization layer;
-- without these grants the policies are unreachable: service_role direct
-- reads/writes fail with "permission denied" and the authenticated clients
-- (web/iOS/Android, which query the recovery projection for the catch-up UI)
-- get nothing at all.
REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE public.integration_recoveries
FROM anon, authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.integration_recoveries
TO service_role;

-- Users may read only their own recovery metadata (enforced by the RLS policy
-- added in 20260802000004); they never mutate it.
GRANT SELECT ON TABLE public.integration_recoveries TO authenticated;

CREATE OR REPLACE FUNCTION public.claim_integration_recovery(
    p_worker_id text,
    p_lock_seconds integer DEFAULT 300
) RETURNS SETOF public.integration_recoveries
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_recovery public.integration_recoveries;
BEGIN
    SELECT * INTO v_recovery
    FROM public.integration_recoveries
    WHERE status IN ('pending', 'processing')
      AND attempts < max_attempts
      AND (next_retry_at IS NULL OR next_retry_at <= now())
      AND (locked_until IS NULL OR locked_until < now())
    ORDER BY requested_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF v_recovery.id IS NULL THEN
        RETURN;
    END IF;

    UPDATE public.integration_recoveries SET
        status = 'processing',
        locked_by = p_worker_id,
        locked_until = now() + make_interval(secs => greatest(p_lock_seconds, 1)),
        attempts = attempts + 1,
        started_at = COALESCE(started_at, now()),
        updated_at = now()
    WHERE id = v_recovery.id
    RETURNING * INTO v_recovery;

    RETURN NEXT v_recovery;
END; $$;

REVOKE ALL ON FUNCTION public.claim_integration_recovery(text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claim_integration_recovery(text, integer) TO service_role;

COMMENT ON FUNCTION public.claim_integration_recovery IS
    'Service-role-only: FOR UPDATE SKIP LOCKED claim of the next pending integration recovery generation (also reclaims expired crashed-worker claims)';
