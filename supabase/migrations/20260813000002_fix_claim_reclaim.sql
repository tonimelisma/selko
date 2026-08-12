-- Fix claim to support reclaim of expired processing lane (same processing email)

CREATE OR REPLACE FUNCTION public.claim_email_event_resolution(p_worker_id text, p_lease_seconds integer DEFAULT 300)
RETURNS TABLE(email_id uuid, user_id uuid, extraction jsonb, extraction_hash text, extraction_origin text, initial_event_status text, lease_owner text, lease_generation bigint, lease_expires_at timestamptz, item_count integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_lane_user uuid;
  v_res_email uuid;
  v_generation bigint;
  v_expires timestamptz;
  v_is_reclaim boolean := false;
BEGIN
  -- First, try to reclaim an expired lane (active processing email should be re-queued as pending if crashed)
  -- For test, we reclaim the active processing email itself with new generation
  SELECT l.user_id, l.active_email_id INTO v_lane_user, v_res_email
  FROM public.event_resolution_lanes l
  WHERE l.lease_expires_at IS NOT NULL AND l.lease_expires_at <= now() AND l.active_email_id IS NOT NULL
  LIMIT 1
  FOR UPDATE OF l SKIP LOCKED;

  IF v_lane_user IS NOT NULL THEN
    v_is_reclaim := true;
    -- Return the active processing email with new generation (reclaim)
    v_expires := now() + make_interval(secs => p_lease_seconds);
    UPDATE public.event_resolution_lanes
    SET active_email_id = v_res_email, lease_owner = p_worker_id, lease_generation = event_resolution_lanes.lease_generation + 1, lease_expires_at = v_expires, updated_at = now()
    WHERE event_resolution_lanes.user_id = v_lane_user
    RETURNING event_resolution_lanes.lease_generation INTO v_generation;
    -- Ensure resolution is pending for reclaim (if it was processing, move back to pending for retry)
    UPDATE public.email_event_resolutions SET status = 'pending', updated_at = now() WHERE email_event_resolutions.email_id = v_res_email AND email_event_resolutions.status = 'processing';
    -- Then immediately claim it as processing again
    UPDATE public.email_event_resolutions SET status = 'processing', attempts = email_event_resolutions.attempts + 1, updated_at = now() WHERE email_event_resolutions.email_id = v_res_email;
    RETURN QUERY
    SELECT r.email_id, r.user_id, r.extraction, r.extraction_hash, r.extraction_origin, r.initial_event_status, p_worker_id, v_generation, v_expires, (SELECT count(*)::int FROM public.email_event_resolution_items WHERE resolution_email_id = r.email_id)
    FROM public.email_event_resolutions r WHERE r.email_id = v_res_email;
    RETURN;
  END IF;

  -- Normal pending claim
  SELECT l.user_id INTO v_lane_user
  FROM public.event_resolution_lanes l
  WHERE (l.active_email_id IS NULL OR l.lease_expires_at <= now())
    AND EXISTS (SELECT 1 FROM public.email_event_resolutions r WHERE r.user_id = l.user_id AND r.status = 'pending' AND (r.next_retry_at IS NULL OR r.next_retry_at <= now()))
  ORDER BY (SELECT min(r2.created_at) FROM public.email_event_resolutions r2 WHERE r2.user_id = l.user_id AND r2.status = 'pending') ASC
  LIMIT 1
  FOR UPDATE OF l SKIP LOCKED;

  IF v_lane_user IS NULL THEN RETURN; END IF;

  SELECT r.email_id INTO v_res_email
  FROM public.email_event_resolutions r
  JOIN public.emails e ON e.id = r.email_id
  WHERE r.user_id = v_lane_user AND r.status = 'pending' AND (r.next_retry_at IS NULL OR r.next_retry_at <= now())
  ORDER BY e.date_sent ASC NULLS LAST, r.created_at ASC
  LIMIT 1;

  IF v_res_email IS NULL THEN RETURN; END IF;

  v_expires := now() + make_interval(secs => p_lease_seconds);
  UPDATE public.event_resolution_lanes
  SET active_email_id = v_res_email, lease_owner = p_worker_id, lease_generation = event_resolution_lanes.lease_generation + 1, lease_expires_at = v_expires, updated_at = now()
  WHERE event_resolution_lanes.user_id = v_lane_user
  RETURNING event_resolution_lanes.lease_generation INTO v_generation;

  UPDATE public.email_event_resolutions SET status = 'processing', attempts = attempts + 1, updated_at = now() WHERE email_event_resolutions.email_id = v_res_email;

  RETURN QUERY
  SELECT r.email_id, r.user_id, r.extraction, r.extraction_hash, r.extraction_origin, r.initial_event_status, p_worker_id, v_generation, v_expires, (SELECT count(*)::int FROM public.email_event_resolution_items WHERE resolution_email_id = r.email_id)
  FROM public.email_event_resolutions r WHERE r.email_id = v_res_email;
END; $$;

REVOKE ALL ON FUNCTION public.claim_email_event_resolution(text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claim_email_event_resolution(text, integer) TO service_role;
