-- Migration: Don't requeue already-skipped emails when an equivalent
-- ignore rule survives the delete.
--
-- reset_skipped_emails_for_sender_rule() (20260213000002) fires on every
-- DELETE of an 'ignore' sender_rules row and resets that sender's skipped
-- emails to pending. The 20260713000001 migration's dedupe step deletes
-- OLDER duplicate 'ignore' rows for the same (user_id, sender_email/domain)
-- before adding the uniqueness constraint — each such DELETE fired this
-- trigger and requeued already-ignored emails even though a newer duplicate
-- 'ignore' rule for the same sender still exists. Guard the trigger: skip
-- the reset when another 'ignore' rule for the same sender still exists.

CREATE OR REPLACE FUNCTION reset_skipped_emails_for_sender_rule()
RETURNS trigger AS $$
DECLARE
    v_count integer := 0;
    v_count_email integer := 0;
    v_count_domain integer := 0;
    v_equivalent_exists boolean;
BEGIN
    -- Only act on ignore rules
    IF OLD.action != 'ignore' THEN
        RETURN OLD;
    END IF;

    -- If another 'ignore' rule for the same sender still exists (e.g. a
    -- duplicate-row cleanup deleted this row but an equivalent one remains),
    -- the sender is still effectively ignored — don't requeue its emails.
    SELECT EXISTS (
        SELECT 1 FROM public.sender_rules
        WHERE user_id = OLD.user_id
          AND action = 'ignore'
          AND id != OLD.id
          AND (
                (OLD.sender_email IS NOT NULL AND sender_email = OLD.sender_email)
             OR (OLD.sender_domain IS NOT NULL AND sender_domain = OLD.sender_domain)
          )
    ) INTO v_equivalent_exists;

    IF v_equivalent_exists THEN
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
