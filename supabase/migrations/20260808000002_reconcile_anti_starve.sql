-- R4 — Reconcile anti-starve: remove next_poll_at > now() gate
--
-- Old predicate required next_poll_at > now() so reconcile never starved a
-- normal poll. In practice it starved reconcile: if normal polls keep failing
-- and re-arming next_poll_at <= now() via fail_sync backoff, weekly reconcile
-- (the only completeness backstop) could be delayed indefinitely while the
-- flapping integration never reaches the >now() window. The lease check
-- (FOR UPDATE SKIP LOCKED already prevents holding:� customer already
-- holds lease excludes both; so if normal poll holds lease, reconcile cannot
-- claim anyway; if normal poll is due but unclaimed, either can win and the
-- other takes next slot.

CREATE OR REPLACE FUNCTION public.claim_due_email_reconciliation(p_worker_id text, p_lease_seconds integer)
RETURNS TABLE (integration_id uuid, user_id uuid, provider text, run_id uuid,
               run_kind text, lease_expires_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_state public.email_sync_state; v_run_id uuid; v_kind text;
BEGIN
    SELECT s.* INTO v_state FROM public.email_sync_state s
    JOIN public.integrations i ON i.id = s.integration_id
    WHERE i.status = 'active'
      AND (s.lease_expires_at IS NULL OR s.lease_expires_at <= now())
      AND (s.last_reconciled_at IS NULL OR s.last_reconciled_at <= now() - interval '1 day')
    ORDER BY s.last_reconciled_at NULLS FIRST, s.next_poll_at
    LIMIT 1 FOR UPDATE OF s SKIP LOCKED;
    IF v_state.integration_id IS NULL THEN RETURN; END IF;
    v_kind := CASE WHEN v_state.last_reconciled_at IS NOT NULL
                        AND v_state.last_reconciled_at <= now() - interval '7 days'
                   THEN 'weekly_reconcile' ELSE 'daily_reconcile' END;
    INSERT INTO public.email_sync_runs (integration_id, user_id, provider, run_kind, status)
    VALUES (v_state.integration_id, v_state.user_id, v_state.provider, v_kind, 'running')
    RETURNING id INTO v_run_id;
    UPDATE public.email_sync_state SET lease_owner = p_worker_id,
        lease_expires_at = now() + make_interval(secs => greatest(p_lease_seconds, 1)),
        last_started_at = now(), updated_at = now()
    WHERE email_sync_state.integration_id = v_state.integration_id;
    RETURN QUERY SELECT v_state.integration_id, v_state.user_id, v_state.provider,
        v_run_id, v_kind, now() + make_interval(secs => greatest(p_lease_seconds, 1));
END; $$;

REVOKE ALL ON FUNCTION public.claim_due_email_reconciliation(text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claim_due_email_reconciliation(text, integer) TO service_role;

COMMENT ON FUNCTION public.claim_due_email_reconciliation(text, integer) IS
  'R4: remove next_poll_at > now() starvation gate — reconcile competes fairly via SKIP LOCKED';
