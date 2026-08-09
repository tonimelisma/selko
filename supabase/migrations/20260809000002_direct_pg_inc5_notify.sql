-- Direct Postgres Inc5 — NOTIFY triggers and listener (idle → keepalives)
-- One channel, one constant payload per work type, row-level AFTER triggers
-- Duplicate (channel, payload) collapse per transaction (§3.1) → one wake per batch

CREATE OR REPLACE FUNCTION public.notify_work_available()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    PERFORM pg_notify('selko_work', TG_ARGV[0]);
    RETURN NULL;
END; $$;

-- emails pending → LLM extraction
DROP TRIGGER IF EXISTS emails_notify_pending ON public.emails;
CREATE TRIGGER emails_notify_pending
    AFTER INSERT OR UPDATE OF processing_status ON public.emails
    FOR EACH ROW WHEN (NEW.processing_status = 'pending')
    EXECUTE FUNCTION public.notify_work_available('email_pending');

-- events approved → calendar sync
DROP TRIGGER IF EXISTS events_notify_approved ON public.events;
CREATE TRIGGER events_notify_approved
    AFTER INSERT OR UPDATE OF status ON public.events
    FOR EACH ROW WHEN (NEW.status = 'approved')
    EXECUTE FUNCTION public.notify_work_available('event_approved');

-- ingestion items pending → acquisition
DROP TRIGGER IF EXISTS items_notify_pending ON public.email_ingestion_items;
CREATE TRIGGER items_notify_pending
    AFTER INSERT OR UPDATE OF acquisition_status ON public.email_ingestion_items
    FOR EACH ROW WHEN (NEW.acquisition_status = 'pending')
    EXECUTE FUNCTION public.notify_work_available('item_pending');

-- attachments pending → attachment fetch
DROP TRIGGER IF EXISTS attachments_notify_pending ON public.attachments;
CREATE TRIGGER attachments_notify_pending
    AFTER INSERT OR UPDATE OF ingestion_status ON public.attachments
    FOR EACH ROW WHEN (NEW.ingestion_status = 'pending')
    EXECUTE FUNCTION public.notify_work_available('attachment_pending');

COMMENT ON FUNCTION public.notify_work_available() IS 'Inc5: work-available notifier for LISTEN selko_work';

