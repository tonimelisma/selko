-- Generalize email storage so Gmail and Outlook share the ingestion pipeline.

ALTER TABLE public.emails
    RENAME COLUMN gmail_id TO provider_message_id;

ALTER TABLE public.emails
    RENAME COLUMN gmail_label_ids TO provider_labels;

ALTER TABLE public.attachments
    RENAME COLUMN gmail_attachment_id TO provider_attachment_id;

ALTER TABLE public.integrations
    RENAME COLUMN last_history_id TO sync_cursor;

ALTER TABLE public.emails
    ADD COLUMN email_provider text NOT NULL DEFAULT 'gmail';

ALTER TABLE public.emails
    DROP CONSTRAINT IF EXISTS emails_user_id_gmail_id_key;

ALTER TABLE public.emails
    ADD CONSTRAINT emails_user_provider_message_key
    UNIQUE (user_id, email_provider, provider_message_id);

ALTER INDEX IF EXISTS public.idx_emails_gmail_id
    RENAME TO idx_emails_provider_message_id;

DROP TRIGGER IF EXISTS parse_gmail_labels_trigger ON public.emails;
DROP FUNCTION IF EXISTS public.parse_gmail_labels();

CREATE OR REPLACE FUNCTION public.parse_provider_labels()
RETURNS trigger
SECURITY INVOKER
SET search_path = ''
AS $$
BEGIN
    NEW.is_spam       := 'SPAM'                = ANY(NEW.provider_labels);
    NEW.is_trash      := 'TRASH'               = ANY(NEW.provider_labels);
    NEW.is_promotions := 'CATEGORY_PROMOTIONS' = ANY(NEW.provider_labels);
    NEW.is_social     := 'CATEGORY_SOCIAL'     = ANY(NEW.provider_labels);
    NEW.is_updates    := 'CATEGORY_UPDATES'   = ANY(NEW.provider_labels);
    NEW.is_forums     := 'CATEGORY_FORUMS'    = ANY(NEW.provider_labels);
    NEW.is_primary    := 'CATEGORY_PERSONAL'  = ANY(NEW.provider_labels);
    NEW.is_important  := 'IMPORTANT'          = ANY(NEW.provider_labels);
    NEW.is_starred    := 'STARRED'             = ANY(NEW.provider_labels);
    NEW.is_unread     := 'UNREAD'              = ANY(NEW.provider_labels);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER parse_provider_labels_trigger
    BEFORE INSERT OR UPDATE OF provider_labels ON public.emails
    FOR EACH ROW EXECUTE FUNCTION public.parse_provider_labels();
