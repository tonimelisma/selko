-- P4: repair authority for reviewed duplicate-event and cancellation fixes.
-- The repair CLI records only identifiers, statuses, and counts.  It never
-- stores event subjects, email bodies, sender names, or provider URLs.

CREATE TABLE IF NOT EXISTS public.event_repair_audit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    -- Deliberately not an FK: a duplicate event is deleted after its UUID is
    -- recorded, and the audit must preserve that identifier permanently.
    event_id uuid,
    action text NOT NULL CHECK (action IN (
        'merge_duplicate_group',
        'merge_source',
        'cancel_event',
        'mark_source_resolved'
    )),
    reason text NOT NULL,
    actor text NOT NULL,
    pre_change jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.event_repair_audit ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.event_repair_audit FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.event_repair_audit TO service_role;
CREATE INDEX IF NOT EXISTS event_repair_audit_user_created_idx
    ON public.event_repair_audit (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS event_repair_audit_event_created_idx
    ON public.event_repair_audit (event_id, created_at DESC);

-- This is the one state transition used by both automatic cancellation and a
-- reviewed repair.  The worker owns the external calendar write; callers only
-- queue the cancellation and advance its generation fence.
CREATE OR REPLACE FUNCTION public.queue_event_cancellation(
    p_event_id uuid,
    p_user_id uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_event public.events;
BEGIN
    SELECT * INTO v_event
    FROM public.events
    WHERE id = p_event_id
      AND user_id = p_user_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'event % is not owned by user %', p_event_id, p_user_id
            USING ERRCODE = 'P0001';
    END IF;

    IF v_event.status = 'cancelled' THEN
        RETURN jsonb_build_object(
            'event_id', v_event.id,
            'status', v_event.status,
            'calendar_sync_action', v_event.calendar_sync_action,
            'calendar_work_generation', v_event.calendar_work_generation,
            'already_cancelled', true
        );
    END IF;

    IF v_event.status IN ('rejected', 'syncing') THEN
        RAISE EXCEPTION 'event % cannot be cancelled from status %', p_event_id, v_event.status
            USING ERRCODE = 'P0001';
    END IF;

    UPDATE public.events
    SET status = 'cancel_queued',
        calendar_sync_action = 'cancel',
        calendar_work_generation = calendar_work_generation + 1,
        sync_attempts = 0,
        next_retry_at = NULL,
        sync_error = NULL,
        updated_at = now()
    WHERE id = p_event_id;

    RETURN jsonb_build_object(
        'event_id', p_event_id,
        'status', 'cancel_queued',
        'calendar_sync_action', 'cancel',
        'calendar_work_generation', v_event.calendar_work_generation + 1,
        'already_cancelled', false
    );
END;
$$;

REVOKE ALL ON FUNCTION public.queue_event_cancellation(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.queue_event_cancellation(uuid, uuid) TO service_role;
COMMENT ON FUNCTION public.queue_event_cancellation(uuid, uuid)
    IS 'P4/C3 canonical local cancellation transition; external calendar work remains worker-owned';
