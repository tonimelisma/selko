-- V7: make every calendar work completion identity an explicit lease.
-- The old undo signature carried source/restore compatibility parameters that
-- belonged to the retired event-level state owner. Remove that overload so a
-- caller cannot revive the old branch by named arguments.

DROP FUNCTION IF EXISTS public.undo_event_and_enqueue_calendar_work(
    uuid, uuid, uuid, jsonb, text, jsonb, text, boolean
);

CREATE FUNCTION public.undo_event_and_enqueue_calendar_work(
    p_event_id uuid,
    p_user_id uuid,
    p_action text DEFAULT NULL,
    p_desired_event jsonb DEFAULT NULL,
    p_expected_provider_revision text DEFAULT NULL,
    p_force_overwrite boolean DEFAULT false
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_event public.events;
    v_item public.calendar_work_items;
    v_status text;
BEGIN
    SELECT * INTO v_event
    FROM public.events
    WHERE id = p_event_id AND user_id = p_user_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'event % is not owned by user %', p_event_id, p_user_id;
    END IF;

    IF p_action IS NOT NULL THEN
        v_item := public._enqueue_calendar_work(
            p_event_id,
            p_user_id,
            p_action,
            p_desired_event,
            p_expected_provider_revision,
            p_force_overwrite,
            CASE WHEN p_action = 'cancel' THEN 'cancel_queued' ELSE 'approved' END
        );
    END IF;

    IF p_action = 'cancel' THEN
        UPDATE public.events
        SET review_status = 'pending_review', updated_at = now()
        WHERE id = p_event_id;
        v_status := 'pending_review';
    ELSE
        UPDATE public.events
        SET status = 'pending_review', review_status = 'pending_review', updated_at = now()
        WHERE id = p_event_id;
        v_status := 'pending_review';
    END IF;

    RETURN jsonb_build_object(
        'status', v_status,
        'work_item_id', v_item.id,
        'generation', v_item.generation
    );
END;
$$;

REVOKE ALL ON FUNCTION public.undo_event_and_enqueue_calendar_work(
    uuid, uuid, text, jsonb, text, boolean
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.undo_event_and_enqueue_calendar_work(
    uuid, uuid, text, jsonb, text, boolean
) TO service_role;
