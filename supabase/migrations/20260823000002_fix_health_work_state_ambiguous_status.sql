-- Fix forward: health_work_state's open-incidents count referenced
-- operational_incidents.status unqualified, which is ambiguous against the
-- function's own RETURNS TABLE OUT parameter of the same name ("status").
-- PL/pgSQL does not catch this at CREATE time; it only surfaces on first
-- execution, which is exactly what caught it here (never against a real
-- database until this staging deploy):
--
--   ERROR: column reference "status" is ambiguous (42702)
--   HINT: It could refer to either a PL/pgSQL variable or a table column.

CREATE OR REPLACE FUNCTION public.health_work_state(p_warning_seconds integer)
RETURNS TABLE (
    status text,
    ready_emails integer,
    processing_emails integer,
    stale_processing_emails integer,
    unclaimable_emails integer,
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
    v_unclaimable integer;
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
    SELECT count(*)::int INTO v_unclaimable
    FROM public.emails
    WHERE processing_status = 'failed'
       OR (processing_status = 'pending' AND attempts >= max_attempts);

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

    SELECT CASE WHEN min(s.next_poll_at) IS NULL THEN NULL
                ELSE GREATEST(0, EXTRACT(EPOCH FROM (now() - min(s.next_poll_at)))::int) END
    INTO v_oldest_next_poll_seconds
    FROM public.email_sync_state s;

    -- Table-qualified: unqualified `status` here is ambiguous against this
    -- function's own RETURNS TABLE OUT parameter of the same name.
    SELECT count(*)::int INTO v_open_incidents
    FROM public.operational_incidents oi
    WHERE oi.status = 'open' AND oi.incident_key LIKE 'email-sync:%';

    v_status := CASE WHEN v_stale_processing > 0
                       OR v_unclaimable > 0
                       OR v_stale_sync_runs > 0
                       OR v_items_dead_letter > 0
                       OR v_attachments_dead_letter > 0
                       OR v_open_incidents > 0
                       OR (v_oldest_next_poll_seconds IS NOT NULL AND v_oldest_next_poll_seconds > p_warning_seconds)
                  THEN 'degraded' ELSE 'ok' END;

    RETURN QUERY SELECT v_status, v_ready, v_processing, v_stale_processing, v_unclaimable,
        v_stale_sync_runs, v_items_pending, v_items_dead_letter, v_attachments_dead_letter,
        v_integrations_due, v_leases_held, v_oldest_next_poll_seconds, v_open_incidents;
END; $$;

REVOKE ALL ON FUNCTION public.health_work_state(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.health_work_state(integer) TO service_role;
COMMENT ON FUNCTION public.health_work_state(integer)
    IS 'S1.4: one counted health RPC; ready/stale/unclaimable predicates are pinned to the claim RPCs in test_schema_contract.py';
