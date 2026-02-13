-- Migration: Retroactive reprocessing when un-ignoring a sender
-- When an ignore rule is deleted, reset matching skipped emails to pending

-- Function: reset skipped emails matching a deleted ignore rule
CREATE OR REPLACE FUNCTION reset_skipped_emails_for_sender_rule()
RETURNS trigger AS $$
DECLARE
    v_count integer := 0;
    v_count_email integer := 0;
    v_count_domain integer := 0;
BEGIN
    -- Only act on ignore rules
    IF OLD.action != 'ignore' THEN
        RETURN OLD;
    END IF;

    -- Reset emails matching exact sender_email (within 30-day window)
    IF OLD.sender_email IS NOT NULL THEN
        UPDATE emails
        SET processing_status = 'pending',
            attempts = 0,
            processing_error = NULL,
            locked_by = NULL,
            locked_until = NULL
        WHERE from_email = OLD.sender_email
          AND user_id = OLD.user_id
          AND processing_status = 'skipped'
          AND date_sent >= now() - interval '30 days';
        GET DIAGNOSTICS v_count_email = ROW_COUNT;
    END IF;

    -- Reset emails matching sender_domain (within 30-day window)
    IF OLD.sender_domain IS NOT NULL THEN
        UPDATE emails
        SET processing_status = 'pending',
            attempts = 0,
            processing_error = NULL,
            locked_by = NULL,
            locked_until = NULL
        WHERE from_email LIKE '%@' || OLD.sender_domain
          AND user_id = OLD.user_id
          AND processing_status = 'skipped'
          AND date_sent >= now() - interval '30 days';
        GET DIAGNOSTICS v_count_domain = ROW_COUNT;
    END IF;

    v_count := v_count_email + v_count_domain;
    IF v_count > 0 THEN
        RAISE LOG 'Un-ignore: reset % skipped emails for rule %', v_count, OLD.id;
    END IF;

    RETURN OLD;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER
   SET search_path = public;

-- Fire BEFORE DELETE so we can match emails before FK cleanup
CREATE TRIGGER sender_rule_before_delete
    BEFORE DELETE ON public.sender_rules
    FOR EACH ROW EXECUTE FUNCTION reset_skipped_emails_for_sender_rule();
