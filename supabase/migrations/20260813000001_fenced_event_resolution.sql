-- R2: staged, fenced event resolution — Workstream B of review-queue-integrity.md
-- Tables: email_event_resolutions, email_event_resolution_items, event_resolution_lanes
-- One lane per user, generation-fenced, no long transaction across LLM.

ALTER TABLE public.emails DROP CONSTRAINT IF EXISTS emails_processing_status_check;
ALTER TABLE public.emails ADD CONSTRAINT emails_processing_status_check
  CHECK (processing_status IN ('pending','processing','resolving','processed','failed'));

CREATE TABLE public.email_event_resolutions (
  email_id uuid PRIMARY KEY REFERENCES public.emails(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  extraction jsonb NOT NULL,
  extraction_hash text NOT NULL,
  extraction_origin text NOT NULL CHECK (extraction_origin IN ('llm','ics')),
  initial_event_status text NOT NULL CHECK (initial_event_status IN ('pending_review','approved')),
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','completed','failed')),
  attempts integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  next_retry_at timestamptz,
  last_error_code text,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.email_event_resolutions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.email_event_resolutions FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.email_event_resolutions TO service_role;
CREATE INDEX email_event_resolutions_ready_idx ON public.email_event_resolutions (status, next_retry_at, created_at) WHERE status = 'pending';
CREATE INDEX email_event_resolutions_user_status_idx ON public.email_event_resolutions (user_id, status);

CREATE TABLE public.email_event_resolution_items (
  resolution_email_id uuid NOT NULL REFERENCES public.email_event_resolutions(email_id) ON DELETE CASCADE,
  item_index integer NOT NULL CHECK (item_index >= 0),
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','completed')),
  resolved_event_id uuid REFERENCES public.events(id) ON DELETE SET NULL,
  resolution_action text CHECK (resolution_action IN ('created','matched','updated','skipped')),
  completed_at timestamptz,
  PRIMARY KEY (resolution_email_id, item_index)
);

ALTER TABLE public.email_event_resolution_items ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.email_event_resolution_items FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.email_event_resolution_items TO service_role;

CREATE TABLE public.event_resolution_lanes (
  user_id uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  active_email_id uuid REFERENCES public.email_event_resolutions(email_id) ON DELETE RESTRICT,
  lease_owner text,
  lease_generation bigint NOT NULL DEFAULT 0,
  lease_expires_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (active_email_id IS NULL AND lease_owner IS NULL AND lease_expires_at IS NULL)
    OR
    (active_email_id IS NOT NULL AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
  )
);

ALTER TABLE public.event_resolution_lanes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.event_resolution_lanes FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.event_resolution_lanes TO service_role;

INSERT INTO public.event_resolution_lanes (user_id)
SELECT id FROM public.users
ON CONFLICT (user_id) DO NOTHING;

CREATE OR REPLACE FUNCTION public.ensure_event_resolution_lane()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  INSERT INTO public.event_resolution_lanes (user_id) VALUES (NEW.id) ON CONFLICT (user_id) DO NOTHING;
  RETURN NEW;
END; $$;

DROP TRIGGER IF EXISTS trg_ensure_event_resolution_lane ON public.users;
CREATE TRIGGER trg_ensure_event_resolution_lane
  AFTER INSERT ON public.users
  FOR EACH ROW EXECUTE FUNCTION public.ensure_event_resolution_lane();

REVOKE ALL ON FUNCTION public.ensure_event_resolution_lane() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.ensure_event_resolution_lane() TO service_role;

CREATE OR REPLACE FUNCTION public.enqueue_email_event_resolution(
  p_email_id uuid,
  p_user_id uuid,
  p_extraction jsonb,
  p_extraction_hash text,
  p_extraction_origin text,
  p_initial_event_status text
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_email_user uuid;
  v_existing_hash text;
  v_existing_status text;
BEGIN
  SELECT user_id INTO v_email_user FROM public.emails WHERE id = p_email_id;
  IF v_email_user IS NULL THEN RAISE EXCEPTION 'email not found: %', p_email_id USING ERRCODE = 'P0001'; END IF;
  IF v_email_user <> p_user_id THEN RAISE EXCEPTION 'email user mismatch' USING ERRCODE = 'P0001'; END IF;
  IF jsonb_array_length(COALESCE(p_extraction, '[]'::jsonb)) = 0 THEN RAISE EXCEPTION 'empty extraction not enqueued' USING ERRCODE = 'P0001'; END IF;

  SELECT extraction_hash, status INTO v_existing_hash, v_existing_status FROM public.email_event_resolutions WHERE email_id = p_email_id;
  IF v_existing_hash IS NOT NULL THEN
    IF v_existing_hash = p_extraction_hash THEN RETURN p_email_id; END IF;
    IF v_existing_status <> 'failed' THEN RAISE EXCEPTION 'conflict: different extraction for non-failed work' USING ERRCODE = '23505'; END IF;
  END IF;

  INSERT INTO public.email_event_resolutions (email_id, user_id, extraction, extraction_hash, extraction_origin, initial_event_status, status)
  VALUES (p_email_id, p_user_id, p_extraction, p_extraction_hash, p_extraction_origin, p_initial_event_status, 'pending')
  ON CONFLICT (email_id) DO UPDATE SET extraction = EXCLUDED.extraction, extraction_hash = EXCLUDED.extraction_hash, extraction_origin = EXCLUDED.extraction_origin, initial_event_status = EXCLUDED.initial_event_status, status = 'pending', attempts = 0, next_retry_at = NULL, last_error_code = NULL, updated_at = now();

  DELETE FROM public.email_event_resolution_items WHERE resolution_email_id = p_email_id;
  INSERT INTO public.email_event_resolution_items (resolution_email_id, item_index)
  SELECT p_email_id, (ord - 1) FROM jsonb_array_elements(p_extraction) WITH ORDINALITY AS t(elem, ord);

  UPDATE public.emails SET processing_status = 'resolving' WHERE id = p_email_id;
  RETURN p_email_id;
END; $$;

REVOKE ALL ON FUNCTION public.enqueue_email_event_resolution(uuid, uuid, jsonb, text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.enqueue_email_event_resolution(uuid, uuid, jsonb, text, text, text) TO service_role;

CREATE OR REPLACE FUNCTION public.claim_email_event_resolution(p_worker_id text, p_lease_seconds integer DEFAULT 300)
RETURNS TABLE(email_id uuid, user_id uuid, extraction jsonb, extraction_hash text, extraction_origin text, initial_event_status text, lease_owner text, lease_generation bigint, lease_expires_at timestamptz, item_count integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_lane_user uuid;
  v_res_email uuid;
  v_generation bigint;
  v_expires timestamptz;
BEGIN
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

CREATE OR REPLACE FUNCTION public.heartbeat_email_event_resolution(p_user_id uuid, p_email_id uuid, p_owner text, p_generation bigint, p_extend_seconds integer DEFAULT 300)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_updated int;
BEGIN
  UPDATE public.event_resolution_lanes
  SET lease_expires_at = now() + make_interval(secs => p_extend_seconds), updated_at = now()
  WHERE user_id = p_user_id AND active_email_id = p_email_id AND lease_owner = p_owner AND lease_generation = p_generation AND lease_expires_at > now();
  GET DIAGNOSTICS v_updated = ROW_COUNT;
  RETURN v_updated = 1;
END; $$;
REVOKE ALL ON FUNCTION public.heartbeat_email_event_resolution(uuid, uuid, text, bigint, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.heartbeat_email_event_resolution(uuid, uuid, text, bigint, integer) TO service_role;

CREATE OR REPLACE FUNCTION public.fail_email_event_resolution(p_user_id uuid, p_email_id uuid, p_owner text, p_generation bigint, p_error_code text, p_retry_after_seconds integer DEFAULT 60)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_attempts int; v_max int;
BEGIN
  PERFORM 1 FROM public.event_resolution_lanes WHERE user_id = p_user_id AND active_email_id = p_email_id AND lease_owner = p_owner AND lease_generation = p_generation AND lease_expires_at > now();
  IF NOT FOUND THEN RETURN false; END IF;
  SELECT attempts, max_attempts INTO v_attempts, v_max FROM public.email_event_resolutions WHERE email_id = p_email_id;
  IF v_attempts >= v_max THEN
    UPDATE public.email_event_resolutions SET status = 'failed', last_error_code = p_error_code, updated_at = now() WHERE email_id = p_email_id;
    UPDATE public.emails SET processing_status = 'failed' WHERE id = p_email_id;
  ELSE
    UPDATE public.email_event_resolutions SET status = 'pending', last_error_code = p_error_code, next_retry_at = now() + make_interval(secs => p_retry_after_seconds), updated_at = now() WHERE email_id = p_email_id;
  END IF;
  UPDATE public.event_resolution_lanes SET active_email_id = NULL, lease_owner = NULL, lease_expires_at = NULL, updated_at = now() WHERE user_id = p_user_id;
  RETURN true;
END; $$;
REVOKE ALL ON FUNCTION public.fail_email_event_resolution(uuid, uuid, text, bigint, text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.fail_email_event_resolution(uuid, uuid, text, bigint, text, integer) TO service_role;

COMMENT ON TABLE public.email_event_resolutions IS 'Staged extractions awaiting fenced per-user resolution (R2)';
COMMENT ON TABLE public.event_resolution_lanes IS 'One lane per user with generation-fenced lease (R2)';

-- RPC: commit_email_event_resolution_item (fenced per-item commit)
CREATE OR REPLACE FUNCTION public.commit_email_event_resolution_item(
  p_user_id uuid,
  p_email_id uuid,
  p_item_index integer,
  p_owner text,
  p_generation bigint,
  p_resolved_event_id uuid,
  p_action text
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_updated int;
BEGIN
  -- Fence: lane must still be owned by this worker/generation and not expired
  PERFORM 1 FROM public.event_resolution_lanes
  WHERE user_id = p_user_id AND active_email_id = p_email_id AND lease_owner = p_owner AND lease_generation = p_generation AND lease_expires_at > now();
  IF NOT FOUND THEN RETURN false; END IF;

  -- Lock item
  PERFORM 1 FROM public.email_event_resolution_items
  WHERE resolution_email_id = p_email_id AND item_index = p_item_index FOR UPDATE;
  IF NOT FOUND THEN RETURN false; END IF;

  -- Idempotent if already completed
  PERFORM 1 FROM public.email_event_resolution_items
  WHERE resolution_email_id = p_email_id AND item_index = p_item_index AND status = 'completed';
  IF FOUND THEN RETURN true; END IF;

  UPDATE public.email_event_resolution_items
  SET status = 'completed', resolved_event_id = p_resolved_event_id, resolution_action = p_action, completed_at = now()
  WHERE resolution_email_id = p_email_id AND item_index = p_item_index;
  GET DIAGNOSTICS v_updated = ROW_COUNT;
  IF v_updated = 0 THEN RETURN false; END IF;

  -- If all items completed, mark resolution and email terminal and release lane
  PERFORM 1 FROM public.email_event_resolution_items
  WHERE resolution_email_id = p_email_id AND status = 'pending';
  IF NOT FOUND THEN
    UPDATE public.email_event_resolutions SET status = 'completed', completed_at = now(), updated_at = now() WHERE email_id = p_email_id;
    UPDATE public.emails SET processing_status = 'processed' WHERE id = p_email_id;
    UPDATE public.event_resolution_lanes SET active_email_id = NULL, lease_owner = NULL, lease_expires_at = NULL, updated_at = now() WHERE user_id = p_user_id;
  END IF;
  RETURN true;
END; $$;
REVOKE ALL ON FUNCTION public.commit_email_event_resolution_item(uuid, uuid, integer, text, bigint, uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.commit_email_event_resolution_item(uuid, uuid, integer, text, bigint, uuid, text) TO service_role;
