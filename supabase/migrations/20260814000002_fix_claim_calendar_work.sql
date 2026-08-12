-- Fix claim_calendar_work regression from R4: restore legacy claim logic
DROP FUNCTION IF EXISTS public.claim_calendar_work(text, integer);
DROP FUNCTION IF EXISTS public.claim_approved_event(text, integer);

CREATE FUNCTION public.claim_calendar_work(p_worker_id text, p_lease_seconds integer DEFAULT 300)
RETURNS SETOF public.events
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_event public.events;
BEGIN
  SELECT * INTO v_event
  FROM public.events
  WHERE status IN ('approved','cancel_queued')
    AND sync_attempts < max_sync_attempts
    AND (locked_until IS NULL OR locked_until < now())
    AND (next_retry_at IS NULL OR next_retry_at <= now())
    AND EXISTS (
      SELECT 1 FROM public.integrations i
      WHERE i.user_id = events.user_id
        AND i.provider = 'google_calendar'
        AND i.status = 'active'
    )
  ORDER BY updated_at ASC
  LIMIT 1
  FOR UPDATE SKIP LOCKED;

  IF v_event.id IS NOT NULL THEN
    UPDATE public.events SET
      status = 'syncing',
      locked_by = p_worker_id,
      locked_until = now() + (p_lease_seconds || ' seconds')::interval,
      sync_attempts = sync_attempts + 1,
      calendar_work_generation = public.events.calendar_work_generation + 1,
      updated_at = now()
    WHERE id = v_event.id
    RETURNING * INTO v_event;

    RETURN NEXT v_event;
  END IF;
END;
$$;
REVOKE ALL ON FUNCTION public.claim_calendar_work(text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claim_calendar_work(text, integer) TO service_role;

CREATE FUNCTION public.claim_approved_event(p_worker_id text, p_lease_seconds integer DEFAULT 300)
RETURNS SETOF public.events
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$ SELECT * FROM public.claim_calendar_work(p_worker_id, p_lease_seconds); $$;
REVOKE ALL ON FUNCTION public.claim_approved_event(text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claim_approved_event(text, integer) TO service_role;
