-- Make a stalled acquisition executor visible to the health rollup.
--
-- Production stopped claiming ingestion work at 2026-09-29T20:55Z and stayed
-- stopped for 19 days while /health reported `status: ok` on every surface.
-- 912 rows sat in email_ingestion_items, every one of them satisfying
-- claim_email_ingestion_item's predicate, with attempts = 0 and no error. The
-- executor had not failed; it had stopped asking, because both of its
-- semaphore permits were held by tasks that never returned.
--
-- Nothing in health_work_state could see that:
--
--   items_pending        counted the backlog but never degraded the rollup
--   items_dead_letter    0 -- nothing ever failed, so nothing dead-lettered
--   unclaimable_pending  about `emails`, not `email_ingestion_items`
--   stale_sync_runs      0 -- discovery was healthy the whole time
--
-- So the queue that was actually stuck was invisible to every gauge that can
-- turn the rollup red. This adds the missing one.
--
-- The hard part is telling a *stalled* executor apart from a legitimately
-- *large* backlog. "Oldest claimable item is older than N" is red during any
-- bulk backfill, and a signal that cries wolf gets ignored exactly as fast as
-- one that cannot fire at all (see 20260901000001, which had to undo a gauge
-- that could never return to zero). So this counts the age only while nothing
-- is being acquired at all: claimable work plus zero in-flight acquisitions is
-- the signature of a stalled executor, and it is not what a draining backlog
-- looks like.
--
-- It returns to green on its own two ways: the backlog drains (no claimable
-- rows -> NULL) or acquisition resumes (an in-flight lease -> 0). Neither
-- needs an operator.

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
    items_stalled_seconds integer,
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
    v_items_acquiring integer;
    v_items_stalled_seconds integer;
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

    -- An item whose lease is still in the future is being worked right now, so
    -- the executor is alive and the backlog is draining rather than stuck.
    SELECT count(*)::int INTO v_items_acquiring
    FROM public.email_ingestion_items
    WHERE acquisition_status = 'processing' AND lease_expires_at > now();

    -- How long claimable acquisition work has been sitting with nothing
    -- acquiring it. The WHERE clause mirrors claim_email_ingestion_item's
    -- predicate exactly -- it has to, or this measures a different queue than
    -- the one the worker drains. Eligibility time is next_retry_at when a row
    -- is serving a backoff and created_at otherwise, so a row waiting out a
    -- legitimate retry delay is not counted as stalled.
    SELECT CASE
               WHEN v_items_acquiring > 0 THEN 0
               WHEN min(COALESCE(i.next_retry_at, i.created_at)) IS NULL THEN NULL
               ELSE GREATEST(0, EXTRACT(EPOCH FROM (
                        now() - min(COALESCE(i.next_retry_at, i.created_at))
                    ))::int)
           END
    INTO v_items_stalled_seconds
    FROM public.email_ingestion_items i
    WHERE i.acquisition_status IN ('pending', 'retry', 'processing')
      AND i.attempts < i.max_attempts
      AND (i.next_retry_at IS NULL OR i.next_retry_at <= now())
      AND (i.lease_expires_at IS NULL OR i.lease_expires_at <= now());

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
                       OR (v_items_stalled_seconds IS NOT NULL AND v_items_stalled_seconds > p_warning_seconds)
                  THEN 'degraded' ELSE 'ok' END;

    RETURN QUERY SELECT v_status, v_ready, v_processing, v_stale_processing, v_unclaimable_pending, v_failed,
        v_stale_sync_runs, v_items_pending, v_items_dead_letter, v_attachments_dead_letter,
        v_items_stalled_seconds, v_integrations_due, v_leases_held, v_oldest_next_poll_seconds,
        v_open_incidents;
END; $$;

REVOKE ALL ON FUNCTION public.health_work_state(integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.health_work_state(integer) TO service_role;
COMMENT ON FUNCTION public.health_work_state(integer)
    IS 'One counted health RPC. unclaimable_pending and items_stalled_seconds are actionable and degrade the rollup; failed_emails and items_pending are history/depth and do not. items_stalled_seconds is NULL with no claimable work and 0 while an acquisition lease is in flight, so it returns to green without operator action. Predicates pinned in test_schema_contract.py';
