-- C7: Broadcast fan-out collapse — one message per (transaction, user, resource).
--
-- realtime.send does NOT deduplicate the way pg_notify does, so the per-row
-- triggers previously emitted one message per row. The payload is an
-- invalidation hint, so one per transaction carries the same information.

CREATE OR REPLACE FUNCTION public.broadcast_user_ui_change(
    p_user_id uuid,
    p_resource text,
    p_operation text,
    p_entity_id uuid
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
    v_payload jsonb;
    v_topic text;
    v_guard text;
BEGIN
    IF p_user_id IS NULL THEN
        RETURN;
    END IF;

    -- Transaction-local GUC as the guard; reset automatically at commit
    -- or rollback, so it cannot leak between transactions on a pooled
    -- connection.
    v_guard := 'selko.bc_' || replace(p_user_id::text, '-', '') || '_' || p_resource;
    IF current_setting(v_guard, true) = '1' THEN
        RETURN;
    END IF;
    PERFORM set_config(v_guard, '1', true);

    v_topic := 'user:' || p_user_id::text || ':selko-changes';
    v_payload := jsonb_build_object(
        'resource', p_resource,
        'operation', p_operation,
        -- entity_id is omitted: consumers refetch the whole resource anyway,
        -- and a single id is misleading when the transaction touched many rows.
        'occurred_at', (now() AT TIME ZONE 'utc')::text
    );
    PERFORM realtime.send(v_payload, 'invalidate', v_topic, true);
END;
$$;

REVOKE ALL ON FUNCTION public.broadcast_user_ui_change(uuid, text, text, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.broadcast_user_ui_change(uuid, text, text, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.broadcast_user_ui_change(uuid, text, text, uuid) TO authenticated;

-- Narrow the events UPDATE trigger: it fired on every column change,
-- including lease churn from the workers (locked_by/locked_until churn
-- emits per-claim broadcasts).
DROP TRIGGER IF EXISTS trg_events_broadcast_upd ON public.events;
CREATE TRIGGER trg_events_broadcast_upd
    AFTER UPDATE OF status, title, start_datetime, end_datetime
    ON public.events
    FOR EACH ROW EXECUTE FUNCTION public.trg_events_broadcast();
