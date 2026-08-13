-- R4: automatic cancellation — Workstream D of review-queue-integrity.md
-- Extends events with calendar_sync_action/generation, status cancel_queued, and updates claim

ALTER TABLE public.events ADD COLUMN IF NOT EXISTS calendar_sync_action text NOT NULL DEFAULT 'upsert' CHECK (calendar_sync_action IN ('upsert','cancel'));
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS calendar_work_generation bigint NOT NULL DEFAULT 0;

ALTER TABLE public.events DROP CONSTRAINT IF EXISTS events_status_check;
ALTER TABLE public.events ADD CONSTRAINT events_status_check
  CHECK (status IN (
    'pending_review','pending_change','approved','rejected','cancelled',
    'cancel_queued','syncing','synced','sync_failed'
  ));

-- Extend email_event_resolutions for cancellation
ALTER TABLE public.email_event_resolutions DROP CONSTRAINT IF EXISTS email_event_resolutions_extraction_origin_check;
ALTER TABLE public.email_event_resolutions ADD CONSTRAINT email_event_resolutions_extraction_origin_check
  CHECK (extraction_origin IN ('llm','ics','structured_cancellation'));
ALTER TABLE public.email_event_resolution_items DROP CONSTRAINT IF EXISTS email_event_resolution_items_resolution_action_check;
ALTER TABLE public.email_event_resolution_items ADD CONSTRAINT email_event_resolution_items_resolution_action_check
  CHECK (resolution_action IN ('created','matched','updated','skipped','cancelled','cancellation_unmatched','cancellation_ambiguous'));

-- Update claim_calendar_work to handle both upsert and cancel
CREATE OR REPLACE FUNCTION public.claim_calendar_work(p_worker_id text, p_lease_seconds integer DEFAULT 300)
RETURNS TABLE(id uuid, user_id uuid, status text, calendar_sync_action text, calendar_work_generation bigint, sync_attempts integer, max_sync_attempts integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  RETURN QUERY
  UPDATE public.events
  SET calendar_work_generation = events.calendar_work_generation + 1,
      sync_attempts = events.sync_attempts + 1,
      updated_at = now()
  WHERE events.id = (
    SELECT e2.id FROM public.events e2
    WHERE e2.status IN ('approved','cancel_queued')
      AND (e2.next_retry_at IS NULL OR e2.next_retry_at <= now())
    ORDER BY e2.created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
  )
  RETURNING events.id, events.user_id, events.status, events.calendar_sync_action, events.calendar_work_generation, events.sync_attempts, events.max_sync_attempts;
END; $$;
REVOKE ALL ON FUNCTION public.claim_calendar_work(text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claim_calendar_work(text, integer) TO service_role;

DROP FUNCTION IF EXISTS public.claim_approved_event(text, integer);
-- Keep old name as wrapper for compat
CREATE OR REPLACE FUNCTION public.claim_approved_event(p_worker_id text, p_lease_seconds integer DEFAULT 300)
RETURNS TABLE(id uuid, user_id uuid, status text, calendar_sync_action text, calendar_work_generation bigint, sync_attempts integer, max_sync_attempts integer)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$ SELECT * FROM public.claim_calendar_work(p_worker_id, p_lease_seconds); $$;
REVOKE ALL ON FUNCTION public.claim_approved_event(text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claim_approved_event(text, integer) TO service_role;

COMMENT ON TABLE public.events IS 'R4: cancel_queued + calendar_sync_action/cancel generation (review-queue-integrity)';
