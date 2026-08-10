-- Live UI Updates — private per-user Broadcast invalidations
-- One topic per user: user:<uid>:selko-changes, payload is invalidation hint only

-- Helper: broadcast minimal invalidation (private=true, event 'invalidate')
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
BEGIN
    IF p_user_id IS NULL THEN
        RETURN;
    END IF;
    v_topic := 'user:' || p_user_id::text || ':selko-changes';
    v_payload := jsonb_build_object(
        'resource', p_resource,
        'operation', p_operation,
        'entity_id', p_entity_id,
        'occurred_at', (now() AT TIME ZONE 'utc')::text
    );
    PERFORM realtime.send(v_payload, 'invalidate', v_topic, true);
END;
$$;

REVOKE ALL ON FUNCTION public.broadcast_user_ui_change(uuid, text, text, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.broadcast_user_ui_change(uuid, text, text, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.broadcast_user_ui_change(uuid, text, text, uuid) TO authenticated;

COMMENT ON FUNCTION public.broadcast_user_ui_change(uuid, text, text, uuid) IS 'Live UI: private per-user Broadcast invalidation (resource/operation/entity_id)';

-- Trigger functions
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
            OR NEW.end_datetime IS DISTINCT FROM OLD.end_datetime
            OR NEW.status IS DISTINCT FROM OLD.status
            OR NEW.sync_status IS DISTINCT FROM OLD.sync_status) THEN
            PERFORM public.broadcast_user_ui_change(NEW.user_id, 'events', 'UPDATE', NEW.id);
        END IF;
        RETURN NEW;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_events_broadcast_ins ON public.events;
CREATE TRIGGER trg_events_broadcast_ins
    AFTER INSERT ON public.events
    FOR EACH ROW EXECUTE FUNCTION public.trg_events_broadcast();

DROP TRIGGER IF EXISTS trg_events_broadcast_upd ON public.events;
CREATE TRIGGER trg_events_broadcast_upd
    AFTER UPDATE ON public.events
    FOR EACH ROW EXECUTE FUNCTION public.trg_events_broadcast();

DROP TRIGGER IF EXISTS trg_events_broadcast_del ON public.events;
CREATE TRIGGER trg_events_broadcast_del
    AFTER DELETE ON public.events
    FOR EACH ROW EXECUTE FUNCTION public.trg_events_broadcast();

CREATE OR REPLACE FUNCTION public.trg_event_sources_broadcast()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_user_id uuid;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT user_id INTO v_user_id FROM public.events WHERE id = NEW.event_id;
        IF v_user_id IS NOT NULL THEN
            PERFORM public.broadcast_user_ui_change(v_user_id, 'event_sources', 'INSERT', NEW.id);
        END IF;
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        IF (NEW.is_undone IS DISTINCT FROM OLD.is_undone
            OR NEW.change_set IS DISTINCT FROM OLD.change_set
            OR NEW.source_origin IS DISTINCT FROM OLD.source_origin) THEN
            SELECT user_id INTO v_user_id FROM public.events WHERE id = NEW.event_id;
            IF v_user_id IS NOT NULL THEN
                PERFORM public.broadcast_user_ui_change(v_user_id, 'event_sources', 'UPDATE', NEW.id);
            END IF;
        END IF;
        RETURN NEW;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_event_sources_broadcast_ins ON public.event_sources;
CREATE TRIGGER trg_event_sources_broadcast_ins
    AFTER INSERT ON public.event_sources
    FOR EACH ROW EXECUTE FUNCTION public.trg_event_sources_broadcast();

DROP TRIGGER IF EXISTS trg_event_sources_broadcast_upd ON public.event_sources;
CREATE TRIGGER trg_event_sources_broadcast_upd
    AFTER UPDATE OF is_undone, change_set, source_origin ON public.event_sources
    FOR EACH ROW EXECUTE FUNCTION public.trg_event_sources_broadcast();

CREATE OR REPLACE FUNCTION public.trg_emails_broadcast()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF (NEW.processing_status IS DISTINCT FROM OLD.processing_status
        OR NEW.processing_error IS DISTINCT FROM OLD.processing_error) THEN
        PERFORM public.broadcast_user_ui_change(NEW.user_id, 'emails', 'UPDATE', NEW.id);
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_emails_broadcast_upd ON public.emails;
CREATE TRIGGER trg_emails_broadcast_upd
    AFTER UPDATE OF processing_status, processing_error ON public.emails
    FOR EACH ROW EXECUTE FUNCTION public.trg_emails_broadcast();

CREATE OR REPLACE FUNCTION public.trg_integrations_broadcast()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF (NEW.status IS DISTINCT FROM OLD.status) THEN
        PERFORM public.broadcast_user_ui_change(NEW.user_id, 'integrations', 'UPDATE', NEW.id);
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_integrations_broadcast_upd ON public.integrations;
CREATE TRIGGER trg_integrations_broadcast_upd
    AFTER UPDATE OF status ON public.integrations
    FOR EACH ROW EXECUTE FUNCTION public.trg_integrations_broadcast();

-- RLS policy for realtime.messages Broadcast private channel
-- Only allow SELECT on own topic; no INSERT for clients
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE policyname = 'live_ui_broadcast_select_own_topic' AND tablename = 'messages' AND schemaname = 'realtime'
    ) THEN
        CREATE POLICY live_ui_broadcast_select_own_topic ON realtime.messages
            FOR SELECT TO authenticated
            USING (
                realtime.messages.extension = 'broadcast'
                AND (SELECT realtime.topic()) = 'user:' || (SELECT auth.uid())::text || ':selko-changes'
            );
    END IF;
END;
$$;

