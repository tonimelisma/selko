-- C5.5: recreate trg_events_broadcast with the duplicated status condition
-- removed and the nonexistent sync_status reference dropped.
--
-- The 20260809000003 original tested NEW.status IS DISTINCT FROM OLD.status
-- twice and referenced NEW.sync_status, a column that has never existed on
-- public.events — every UPDATE on events raised
-- 'record "new" has no field "sync_status"'.

CREATE OR REPLACE FUNCTION public.trg_events_broadcast()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM public.broadcast_user_ui_change(NEW.user_id, 'events', 'INSERT', NEW.id);
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM public.broadcast_user_ui_change(OLD.user_id, 'events', 'DELETE', OLD.id);
        RETURN OLD;
    ELSIF TG_OP = 'UPDATE' THEN
        IF (NEW.status IS DISTINCT FROM OLD.status
            OR NEW.title IS DISTINCT FROM OLD.title
            OR NEW.start_datetime IS DISTINCT FROM OLD.start_datetime
            OR NEW.end_datetime IS DISTINCT FROM OLD.end_datetime) THEN
            PERFORM public.broadcast_user_ui_change(NEW.user_id, 'events', 'UPDATE', NEW.id);
        END IF;
        RETURN NEW;
    END IF;
    RETURN NEW;
END;
$$;
