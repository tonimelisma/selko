-- Migration: Retroactive, atomic sender ignore
--
-- Creating an 'ignore' rule must simultaneously reject that sender's pending
-- events in the New lane AND discard their proposals in the Changes lane,
-- server-side, in one call. Previously the web client looped over only the
-- one lane the button was clicked from.
--
-- `sender_rules` had no uniqueness constraint and no `updated_at` column
-- despite docs/database-schema.md documenting both — add them here so the
-- RPC below can safely upsert.

-- De-duplicate any pre-existing rows before adding uniqueness constraints
-- (keep the most recently created row per match key).
-- These deletes are maintenance, not an explicit un-ignore. Suppress the
-- BEFORE DELETE requeue trigger while duplicates are removed; otherwise the
-- surviving equivalent ignore rule remains active but its skipped emails are
-- incorrectly reset to pending.
ALTER TABLE public.sender_rules DISABLE TRIGGER sender_rule_before_delete;

DELETE FROM public.sender_rules a USING public.sender_rules b
WHERE a.sender_email IS NOT NULL
  AND a.sender_email = b.sender_email
  AND a.user_id = b.user_id
  AND (a.created_at, a.id) < (b.created_at, b.id);

DELETE FROM public.sender_rules a USING public.sender_rules b
WHERE a.sender_domain IS NOT NULL
  AND a.sender_domain = b.sender_domain
  AND a.user_id = b.user_id
  AND (a.created_at, a.id) < (b.created_at, b.id);

ALTER TABLE public.sender_rules ENABLE TRIGGER sender_rule_before_delete;

ALTER TABLE public.sender_rules
    ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now() NOT NULL;

CREATE TRIGGER set_sender_rules_updated_at
    BEFORE UPDATE ON public.sender_rules
    FOR EACH ROW
    EXECUTE FUNCTION public.set_updated_at();

CREATE UNIQUE INDEX IF NOT EXISTS sender_rules_user_email_unique
    ON public.sender_rules(user_id, sender_email)
    WHERE sender_email IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS sender_rules_user_domain_unique
    ON public.sender_rules(user_id, sender_domain)
    WHERE sender_domain IS NOT NULL;

CREATE OR REPLACE FUNCTION public.ignore_sender_and_reject_pending(
    p_sender_email text DEFAULT NULL,
    p_sender_domain text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_user_id uuid := auth.uid();
    v_rejected_new integer := 0;
    v_discarded_changes integer := 0;
    v_event record;
    v_source record;
    v_snapshot jsonb;
    v_has_invitation boolean;
    v_restore_status text;
BEGIN
    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'not authenticated';
    END IF;
    IF p_sender_email IS NULL AND p_sender_domain IS NULL THEN
        RAISE EXCEPTION 'sender_email or sender_domain required';
    END IF;

    -- 1. Upsert the ignore rule.
    IF p_sender_email IS NOT NULL THEN
        INSERT INTO public.sender_rules (user_id, sender_email, action)
        VALUES (v_user_id, p_sender_email, 'ignore')
        ON CONFLICT (user_id, sender_email) WHERE sender_email IS NOT NULL
        DO UPDATE SET action = 'ignore', updated_at = now();
    ELSE
        INSERT INTO public.sender_rules (user_id, sender_domain, action)
        VALUES (v_user_id, p_sender_domain, 'ignore')
        ON CONFLICT (user_id, sender_domain) WHERE sender_domain IS NOT NULL
        DO UPDATE SET action = 'ignore', updated_at = now();
    END IF;

    -- 2. New lane: reject pending_review events that have a non-undone email
    --    source from this sender.
    WITH matching AS (
        SELECT DISTINCT es.event_id
        FROM public.event_sources es
        JOIN public.emails em ON em.id = es.email_id
        WHERE es.is_undone = false
          AND em.user_id = v_user_id
          AND (
                (p_sender_email IS NOT NULL AND em.from_email = p_sender_email)
             OR (p_sender_domain IS NOT NULL
                 AND em.from_email LIKE '%@' || p_sender_domain)
          )
    )
    UPDATE public.events ev
    SET status = 'rejected', updated_at = now()
    FROM matching m
    WHERE ev.id = m.event_id
      AND ev.user_id = v_user_id
      AND ev.status = 'pending_review';
    GET DIAGNOSTICS v_rejected_new = ROW_COUNT;

    -- 3. Changes lane: for each pending_change event whose ACTIVE proposal
    --    (latest non-undone update/cancellation source) came from this sender,
    --    discard the proposal. Mirrors selko.services.events.reject_pending_change.
    FOR v_event IN
        SELECT ev.*
        FROM public.events ev
        WHERE ev.user_id = v_user_id AND ev.status = 'pending_change'
    LOOP
        SELECT es.* INTO v_source
        FROM public.event_sources es
        LEFT JOIN public.emails em ON em.id = es.email_id
        WHERE es.event_id = v_event.id
          AND es.source_type IN ('update', 'cancellation')
          AND es.is_undone = false
        ORDER BY es.created_at DESC
        LIMIT 1;

        IF v_source.id IS NULL THEN CONTINUE; END IF;

        -- Active proposal must be from the ignored sender. The proposal may be
        -- represented by a google_calendar sibling row; check the email sibling.
        IF NOT EXISTS (
            SELECT 1 FROM public.event_sources es2
            JOIN public.emails em2 ON em2.id = es2.email_id
            WHERE es2.event_id = v_event.id
              AND es2.is_undone = false
              AND es2.source_type IN ('update', 'cancellation')
              AND (
                    (p_sender_email IS NOT NULL AND em2.from_email = p_sender_email)
                 OR (p_sender_domain IS NOT NULL
                     AND em2.from_email LIKE '%@' || p_sender_domain)
              )
        ) THEN
            CONTINUE;
        END IF;

        -- Mark ALL active update/cancellation sources undone (email + gcal sibling).
        UPDATE public.event_sources
        SET is_undone = true
        WHERE event_id = v_event.id
          AND source_type IN ('update', 'cancellation')
          AND is_undone = false;

        SELECT EXISTS (
            SELECT 1 FROM public.event_sources
            WHERE event_id = v_event.id AND source_type = 'new_invitation'
        ) INTO v_has_invitation;

        -- GCal-adopt row that only exists to carry this proposal: delete it.
        IF v_event.google_calendar_event_id IS NOT NULL
           AND v_event.synced_at IS NULL
           AND NOT v_has_invitation THEN
            DELETE FROM public.events WHERE id = v_event.id;
            v_discarded_changes := v_discarded_changes + 1;
            CONTINUE;
        END IF;

        -- Restore snapshot fields + status.
        v_snapshot := v_source.event_snapshot_before;
        v_restore_status := CASE
            WHEN v_snapshot ? 'status' AND (v_snapshot->>'status') IN
                 ('pending_review','approved','synced','sync_failed','rejected','cancelled')
                THEN v_snapshot->>'status'
            WHEN v_event.google_calendar_event_id IS NOT NULL THEN 'synced'
            ELSE 'approved'
        END;

        UPDATE public.events SET
            status = v_restore_status,
            title = COALESCE(v_snapshot->>'title', title),
            start_datetime = COALESCE((v_snapshot->>'start_datetime')::timestamptz, start_datetime),
            end_datetime = CASE WHEN v_snapshot ? 'end_datetime'
                THEN (v_snapshot->>'end_datetime')::timestamptz ELSE end_datetime END,
            all_day = COALESCE((v_snapshot->>'all_day')::boolean, all_day),
            location = CASE WHEN v_snapshot ? 'location'
                THEN v_snapshot->>'location' ELSE location END,
            description = CASE WHEN v_snapshot ? 'description'
                THEN v_snapshot->>'description' ELSE description END,
            importance = COALESCE(v_snapshot->>'importance', importance),
            updated_at = now()
        WHERE id = v_event.id;
        v_discarded_changes := v_discarded_changes + 1;
    END LOOP;

    RETURN jsonb_build_object(
        'rejected_new', v_rejected_new,
        'discarded_changes', v_discarded_changes
    );
END;
$$;

GRANT EXECUTE ON FUNCTION public.ignore_sender_and_reject_pending(text, text)
    TO authenticated;
