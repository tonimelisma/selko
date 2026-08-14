-- Keep the event status and its active proposal in one transaction.
-- A pending_change row without an active update/cancellation source cannot be
-- rendered or acted on, and previously survived as a permanently broken card.

CREATE OR REPLACE FUNCTION public.enforce_pending_change_proposal()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_event_id uuid;
BEGIN
    IF TG_TABLE_NAME = 'events' THEN
        v_event_id := COALESCE(NEW.id, OLD.id);
    ELSE
        v_event_id := COALESCE(NEW.event_id, OLD.event_id);
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.events
        WHERE id = v_event_id AND status = 'pending_change'
    ) AND NOT EXISTS (
        SELECT 1
        FROM public.event_sources
        WHERE event_id = v_event_id
          AND source_type IN ('update', 'cancellation')
          AND is_undone = false
    ) THEN
        RAISE EXCEPTION 'pending_change event % requires an active proposal', v_event_id
            USING ERRCODE = '23514';
    END IF;

    RETURN COALESCE(NEW, OLD);
END;
$$;

REVOKE ALL ON FUNCTION public.enforce_pending_change_proposal() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.enforce_pending_change_proposal() TO service_role;

DROP TRIGGER IF EXISTS events_pending_change_proposal_check ON public.events;
CREATE CONSTRAINT TRIGGER events_pending_change_proposal_check
    AFTER INSERT OR UPDATE ON public.events
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION public.enforce_pending_change_proposal();

DROP TRIGGER IF EXISTS event_sources_pending_change_proposal_check ON public.event_sources;
CREATE CONSTRAINT TRIGGER event_sources_pending_change_proposal_check
    AFTER INSERT OR UPDATE OR DELETE ON public.event_sources
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION public.enforce_pending_change_proposal();

CREATE OR REPLACE FUNCTION public.apply_pending_event_change(
    p_event_id uuid,
    p_user_id uuid,
    p_source_id uuid,
    p_title text,
    p_start_datetime timestamptz,
    p_end_datetime timestamptz,
    p_all_day boolean,
    p_location text,
    p_description text,
    p_importance text,
    p_next_status text,
    p_calendar_sync_action text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_event public.events;
    v_latest_source_id uuid;
BEGIN
    SELECT * INTO v_event
    FROM public.events
    WHERE id = p_event_id AND user_id = p_user_id
    FOR UPDATE;

    IF NOT FOUND OR v_event.status <> 'pending_change' THEN
        RAISE EXCEPTION 'event % is not an owned pending_change event', p_event_id
            USING ERRCODE = 'P0001';
    END IF;

    SELECT id INTO v_latest_source_id
    FROM public.event_sources
    WHERE event_id = p_event_id
      AND source_type IN ('update', 'cancellation')
      AND is_undone = false
    ORDER BY created_at DESC, id DESC
    LIMIT 1
    FOR UPDATE;

    IF v_latest_source_id IS NULL OR v_latest_source_id <> p_source_id THEN
        RAISE EXCEPTION 'pending change proposal for event % changed before apply', p_event_id
            USING ERRCODE = '40001';
    END IF;
    IF p_next_status NOT IN ('approved', 'cancel_queued', 'cancelled') THEN
        RAISE EXCEPTION 'invalid applied status %', p_next_status USING ERRCODE = '22023';
    END IF;
    IF p_calendar_sync_action NOT IN ('upsert', 'cancel') THEN
        RAISE EXCEPTION 'invalid calendar sync action %', p_calendar_sync_action USING ERRCODE = '22023';
    END IF;

    UPDATE public.events
    SET title = p_title,
        start_datetime = p_start_datetime,
        end_datetime = p_end_datetime,
        all_day = p_all_day,
        location = p_location,
        description = p_description,
        importance = p_importance,
        status = p_next_status,
        calendar_sync_action = p_calendar_sync_action,
        sync_attempts = 0,
        updated_at = now()
    WHERE id = p_event_id;

    RETURN jsonb_build_object(
        'event_id', p_event_id,
        'source_id', p_source_id,
        'status', p_next_status,
        'calendar_sync_action', p_calendar_sync_action
    );
END;
$$;

REVOKE ALL ON FUNCTION public.apply_pending_event_change(
    uuid, uuid, uuid, text, timestamptz, timestamptz, boolean, text, text,
    text, text, text
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.apply_pending_event_change(
    uuid, uuid, uuid, text, timestamptz, timestamptz, boolean, text, text,
    text, text, text
) TO service_role;

CREATE OR REPLACE FUNCTION public.reject_pending_event_change(
    p_event_id uuid,
    p_user_id uuid,
    p_source_id uuid,
    p_delete_event boolean,
    p_restore_status text,
    p_title text,
    p_start_datetime timestamptz,
    p_end_datetime timestamptz,
    p_all_day boolean,
    p_location text,
    p_description text,
    p_importance text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_event public.events;
    v_latest_source_id uuid;
BEGIN
    SELECT * INTO v_event
    FROM public.events
    WHERE id = p_event_id AND user_id = p_user_id
    FOR UPDATE;

    IF NOT FOUND OR v_event.status <> 'pending_change' THEN
        RAISE EXCEPTION 'event % is not an owned pending_change event', p_event_id
            USING ERRCODE = 'P0001';
    END IF;

    SELECT id INTO v_latest_source_id
    FROM public.event_sources
    WHERE event_id = p_event_id
      AND source_type IN ('update', 'cancellation')
      AND is_undone = false
    ORDER BY created_at DESC, id DESC
    LIMIT 1
    FOR UPDATE;

    IF v_latest_source_id IS NULL OR v_latest_source_id <> p_source_id THEN
        RAISE EXCEPTION 'pending change proposal for event % changed before reject', p_event_id
            USING ERRCODE = '40001';
    END IF;

    IF p_delete_event THEN
        IF v_event.google_calendar_event_id IS NULL OR v_event.synced_at IS NOT NULL THEN
            RAISE EXCEPTION 'event % is not an unsynced calendar-only proposal', p_event_id
                USING ERRCODE = 'P0001';
        END IF;
        DELETE FROM public.events WHERE id = p_event_id;
        RETURN jsonb_build_object('event_id', p_event_id, 'status', 'deleted');
    END IF;

    IF p_restore_status NOT IN (
        'pending_review', 'approved', 'synced', 'sync_failed', 'rejected', 'cancelled'
    ) THEN
        RAISE EXCEPTION 'invalid restored status %', p_restore_status USING ERRCODE = '22023';
    END IF;

    UPDATE public.event_sources
    SET is_undone = true
    WHERE id = p_source_id;

    UPDATE public.events
    SET status = p_restore_status,
        title = p_title,
        start_datetime = p_start_datetime,
        end_datetime = p_end_datetime,
        all_day = p_all_day,
        location = p_location,
        description = p_description,
        importance = p_importance,
        updated_at = now()
    WHERE id = p_event_id;

    RETURN jsonb_build_object(
        'event_id', p_event_id,
        'source_id', p_source_id,
        'status', p_restore_status
    );
END;
$$;

REVOKE ALL ON FUNCTION public.reject_pending_event_change(
    uuid, uuid, uuid, boolean, text, text, timestamptz, timestamptz, boolean,
    text, text, text
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.reject_pending_event_change(
    uuid, uuid, uuid, boolean, text, text, timestamptz, timestamptz, boolean,
    text, text, text
) TO service_role;

COMMENT ON FUNCTION public.apply_pending_event_change(
    uuid, uuid, uuid, text, timestamptz, timestamptz, boolean, text, text,
    text, text, text
) IS 'Atomically validates and applies the latest active event change proposal';
COMMENT ON FUNCTION public.reject_pending_event_change(
    uuid, uuid, uuid, boolean, text, text, timestamptz, timestamptz, boolean,
    text, text, text
) IS 'Atomically rejects the latest active event change proposal and restores event state';
