-- Split the unclaimable rollup into a historical count and an actionable one.
--
-- `unclaimable_emails` counted two unrelated things:
--
--   processing_status = 'failed'                          -- terminal, permanent
--   processing_status = 'pending' AND attempts >= max     -- stuck, actionable
--
-- The first is the normal end state written by fail_email_processing once an
-- email exhausts its retries. Those rows live forever, so a single permanently
-- failed email made the rollup non-zero for good: /health reported 'degraded'
-- permanently, and assert-health.sh -- which calls this condition "NEVER
-- acceptable" -- became unsatisfiable without manual surgery.
--
-- A gate that cannot succeed trains people to ignore it exactly as reliably as
-- one that cannot fail. Production was carrying 27 of these and nobody looked.
--
-- After this split:
--   failed_emails        informational; terminal failures, expected to be > 0
--   unclaimable_pending  actionable; a pending row the claim RPC will never
--                        take. Guaranteed impossible by
--                        emails_pending_is_claimable_check, so a non-zero value
--                        means that invariant has been violated and is worth
--                        waking someone for.
--
-- Only unclaimable_pending degrades the rollup.

DROP FUNCTION IF EXISTS public.health_work_state(integer);

CREATE FUNCTION public.health_work_state(p_warning_seconds integer)
RETURNS TABLE (
    status text,
    ready_emails integer,
    processing_emails integer,
    stale_processing_emails integer,
    unclaimable_pending integer,
    failed_emails integer,
    stale_sync_runs integer,
    items_pending integer,
    items_dead_letter integer,
    attachments_dead_letter integer,
    integrations_due integer,
    leases_held integer,
    oldest_next_poll_seconds integer,
    open_incidents integer
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_ready integer;
    v_processing integer;
    v_stale_processing integer;
    v_unclaimable_pending integer;
    v_failed integer;
    v_stale_sync_runs integer;
    v_items_pending integer;
    v_items_dead_letter integer;
    v_attachments_dead_letter integer;
    v_integrations_due integer;
    v_leases_held integer;
    v_oldest_next_poll_seconds integer;
    v_open_incidents integer;
    v_status text;
BEGIN
    -- Mirrors claim_unprocessed_email's pending-claim predicate exactly.
    SELECT count(*)::int INTO v_ready
    FROM public.emails e
    WHERE e.processing_status = 'pending'
      AND e.attempts < e.max_attempts
      AND (e.locked_until IS NULL OR e.locked_until < now())
      AND (e.next_retry_at IS NULL OR e.next_retry_at <= now())
      AND NOT EXISTS (
          SELECT 1 FROM public.attachments a
          WHERE a.email_id = e.id AND a.ingestion_status IN ('pending', 'processing', 'retry')
      );

    SELECT count(*)::int INTO v_processing FROM public.emails WHERE processing_status = 'processing';

    SELECT count(*)::int INTO v_stale_processing
    FROM public.emails
    WHERE processing_status = 'processing'
      AND (locked_until IS NULL OR locked_until < now());

    -- A row the claim RPC will never pick up again without operator action:
    -- terminally failed and dead-lettered, or a legacy pending row that still
    -- violates the claimability invariant despite the migration backfill.
    -- Actionable: a pending row the claim RPC will never pick up again.
    -- emails_pending_is_claimable_check makes this impossible, so a non-zero
    -- value means that invariant has been violated.
    SELECT count(*)::int INTO v_unclaimable_pending
    FROM public.emails
    WHERE processing_status = 'pending' AND attempts >= max_attempts;

    -- Informational: terminal failures written by fail_email_processing once
    -- retries are exhausted. Permanent, and expected to be non-zero on any
    -- long-running deployment.
    SELECT count(*)::int INTO v_failed
    FROM public.emails
    WHERE processing_status = 'failed';

    SELECT count(*)::int INTO v_stale_sync_runs
    FROM public.email_sync_runs r
    JOIN public.email_sync_state s ON s.integration_id = r.integration_id
    WHERE r.status = 'running'
      AND (s.lease_expires_at IS NULL OR s.lease_expires_at < now());

    SELECT count(*)::int INTO v_items_dead_letter FROM public.email_ingestion_items WHERE acquisition_status = 'dead_letter';
    SELECT count(*)::int INTO v_items_pending FROM public.email_ingestion_items WHERE acquisition_status IN ('pending', 'retry', 'processing');
    SELECT count(*)::int INTO v_attachments_dead_letter FROM public.attachments WHERE ingestion_status = 'dead_letter';

    SELECT count(*)::int INTO v_integrations_due
    FROM public.email_sync_state s
    JOIN public.integrations i ON i.id = s.integration_id
    WHERE i.status = 'active' AND s.next_poll_at <= now()
      AND (s.lease_expires_at IS NULL OR s.lease_expires_at <= now());

    SELECT count(*)::int INTO v_leases_held FROM public.email_sync_state WHERE lease_expires_at > now();

    -- Only active integrations are eligible for provider polling. Keep this
    -- predicate aligned with integrations_due so an expired integration's
    -- historical cursor cannot degrade service health.
    SELECT CASE WHEN min(s.next_poll_at) IS NULL THEN NULL
                ELSE GREATEST(0, EXTRACT(EPOCH FROM (now() - min(s.next_poll_at)))::int) END
    INTO v_oldest_next_poll_seconds
    FROM public.email_sync_state s
    JOIN public.integrations i ON i.id = s.integration_id
    WHERE i.status = 'active';

    -- Table-qualified: unqualified `status` here is ambiguous against this
    -- function's own RETURNS TABLE OUT parameter of the same name.
    SELECT count(*)::int INTO v_open_incidents
    FROM public.operational_incidents oi
    WHERE oi.status = 'open' AND oi.incident_key LIKE 'email-sync:%';

    v_status := CASE WHEN v_stale_processing > 0
                       OR v_unclaimable_pending > 0
                       OR v_stale_sync_runs > 0
                       OR v_items_dead_letter > 0
                       OR v_attachments_dead_letter > 0
                       OR v_open_incidents > 0
                       OR (v_oldest_next_poll_seconds IS NOT NULL AND v_oldest_next_poll_seconds > p_warning_seconds)
                  THEN 'degraded' ELSE 'ok' END;

    RETURN QUERY SELECT v_status, v_ready, v_processing, v_stale_processing, v_unclaimable_pending, v_failed,
        v_stale_sync_runs, v_items_pending, v_items_dead_letter, v_attachments_dead_letter,
        v_integrations_due, v_leases_held, v_oldest_next_poll_seconds, v_open_incidents;
END; $$;

REVOKE ALL ON FUNCTION public.health_work_state(integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.health_work_state(integer) TO service_role;
COMMENT ON FUNCTION public.health_work_state(integer)
    IS 'S1.4: one counted health RPC. unclaimable_pending is actionable and degrades the rollup; failed_emails is terminal history and does not. Predicates pinned in test_schema_contract.py';
