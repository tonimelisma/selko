-- R1 — Health lies → counted health (no 1000-row truncation)
--
-- health_snapshot() used to pull every row and sum in Python over a
-- PostgREST response truncated at 1000. Past ~1k dead letters the endpoint
-- reported status=ok while dead. Fix: server-side counts, one RPC, no
-- truncation. Same cost at 1 or 100k rows.

-- Dead-letter counts: transactional, not truncated
CREATE OR REPLACE FUNCTION public.health_dead_letter_counts()
RETURNS TABLE (items_dead_letter integer, attachments_dead_letter integer, items_pending integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  RETURN QUERY
  SELECT
    (SELECT count(*)::int FROM public.email_ingestion_items
       WHERE acquisition_status = 'dead_letter'),
    (SELECT count(*)::int FROM public.attachments
       WHERE ingestion_status = 'dead_letter'),
    (SELECT count(*)::int FROM public.email_ingestion_items
       WHERE acquisition_status IN ('pending','retry','processing'));
END; $$;

REVOKE ALL ON FUNCTION public.health_dead_letter_counts() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.health_dead_letter_counts() TO service_role;

-- Poll SLO + incidents: due/lease/oldest/incidents counted server-side
CREATE OR REPLACE FUNCTION public.health_poll_slo(p_warning_seconds integer)
RETURNS TABLE (integrations_due integer, leases_held integer,
               oldest_next_poll_seconds integer, open_incidents integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  RETURN QUERY
  SELECT
    (SELECT count(*)::int FROM public.email_sync_state s
       JOIN public.integrations i ON i.id = s.integration_id
       WHERE i.status = 'active'
         AND s.next_poll_at <= now()
         AND (s.lease_expires_at IS NULL OR s.lease_expires_at <= now())),
    (SELECT count(*)::int FROM public.email_sync_state WHERE lease_expires_at > now()),
    (SELECT CASE WHEN min(s.next_poll_at) IS NULL THEN NULL
              ELSE GREATEST(0, EXTRACT(EPOCH FROM (now() - min(s.next_poll_at)))::int) END
       FROM public.email_sync_state s),
    (SELECT count(*)::int FROM public.operational_incidents
       WHERE status = 'open' AND incident_key LIKE 'email-sync:%');
END; $$;

REVOKE ALL ON FUNCTION public.health_poll_slo(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.health_poll_slo(integer) TO service_role;

COMMENT ON FUNCTION public.health_dead_letter_counts() IS
  'R1: counted dead-letter + pending for /health/ingestion — replaces sum() over truncated response';
COMMENT ON FUNCTION public.health_poll_slo(integer) IS
  'R1: counted SLO for /health/ingestion — one RPC, no row shipping, no truncation';
