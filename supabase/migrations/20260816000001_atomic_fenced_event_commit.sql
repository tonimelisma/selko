-- Atomic, lease-fenced commit for extracted calendar events.
--
-- Extraction is deliberately parallel.  The worker reads and computes outside
-- a transaction, then submits one decision envelope here.  The email row is
-- locked first, so a timed-out worker cannot commit after its lease has been
-- reclaimed.  The decision shape is:
--
-- {"action":"create|update|noop", "event_id":"uuid|null",
--  "fields":{}, "source":{"email_id":"uuid", "extracted_data":{}}}
--
-- source may additionally contain source_type, source_origin,
-- google_calendar_source_event_id, event_snapshot_before, change_set, and
-- extra_sources.  Those extensions keep the existing New and Changes lanes
-- in the same transaction without changing the public minimum contract.

ALTER TABLE public.emails
    ADD COLUMN IF NOT EXISTS lock_generation bigint NOT NULL DEFAULT 0;

-- This is the current claim predicate copied byte-for-byte from the durable
-- ingestion migration.  Only the generation increment is new; the WHERE
-- clause must remain identical so claiming semantics cannot drift.
CREATE OR REPLACE FUNCTION public.claim_unprocessed_email(
    p_worker_id text,
    p_lock_duration_seconds integer DEFAULT 300
) RETURNS SETOF public.emails
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_email public.emails;
BEGIN
    SELECT e.* INTO v_email
    FROM public.emails e
    WHERE e.processing_status = 'pending'
      AND e.attempts < e.max_attempts
      AND (e.locked_until IS NULL OR e.locked_until < now())
      AND (e.next_retry_at IS NULL OR e.next_retry_at <= now())
      AND NOT EXISTS (
          SELECT 1 FROM public.attachments a
          WHERE a.email_id = e.id
            AND a.ingestion_status IN ('pending', 'processing', 'retry')
      )
    ORDER BY e.date_sent ASC NULLS LAST, e.created_at ASC
    LIMIT 1 FOR UPDATE SKIP LOCKED;
    IF v_email.id IS NOT NULL THEN
        UPDATE public.emails SET processing_status = 'processing',
            processing_error = NULL,
            locked_by = p_worker_id,
            locked_until = now() + make_interval(secs => greatest(p_lock_duration_seconds, 1)),
            attempts = attempts + 1,
            lock_generation = lock_generation + 1
        WHERE id = v_email.id RETURNING * INTO v_email;
        RETURN NEXT v_email;
    END IF;
END; $$;

COMMENT ON FUNCTION public.claim_unprocessed_email(text, integer)
    IS 'Atomically claim next pending email for LLM processing, incrementing its lease generation';

CREATE OR REPLACE FUNCTION public.commit_email_extraction(
    p_email_id uuid,
    p_worker_id text,
    p_generation bigint,
    p_decisions jsonb,
    p_terminal text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_email public.emails;
    v_decision jsonb;
    v_extra jsonb;
    v_source jsonb;
    v_fields jsonb;
    v_action text;
    v_source_origin text;
    v_source_type text;
    v_event_id uuid;
    v_google_source_id text;
    v_applied integer := 0;
    v_event_ids jsonb := '[]'::jsonb;
BEGIN
    IF p_terminal NOT IN ('processed', 'skipped', 'failed') THEN
        RAISE EXCEPTION 'invalid extraction terminal status: %', p_terminal;
    END IF;

    SELECT * INTO v_email
    FROM public.emails
    WHERE id = p_email_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'email % not found', p_email_id;
    END IF;

    IF v_email.locked_by IS DISTINCT FROM p_worker_id
       OR v_email.lock_generation IS DISTINCT FROM p_generation THEN
        RETURN jsonb_build_object('fenced', true, 'applied', 0);
    END IF;

    FOR v_decision IN
        SELECT value FROM jsonb_array_elements(COALESCE(p_decisions, '[]'::jsonb))
    LOOP
        v_action := v_decision->>'action';
        IF v_action NOT IN ('create', 'update', 'noop') THEN
            RAISE EXCEPTION 'invalid extraction decision action: %', v_action;
        END IF;
        IF v_action = 'noop' THEN
            CONTINUE;
        END IF;

        v_fields := COALESCE(v_decision->'fields', '{}'::jsonb);
        v_source := COALESCE(v_decision->'source', '{}'::jsonb);
        v_source_origin := COALESCE(v_source->>'source_origin', 'email');
        v_source_type := COALESCE(v_source->>'source_type', 'new_invitation');
        v_google_source_id := v_source->>'google_calendar_source_event_id';

        IF v_action = 'create' THEN
            INSERT INTO public.events (
                user_id, title, start_datetime, end_datetime, all_day,
                location, description, importance, status,
                recurrence_rule, google_calendar_event_id
            ) VALUES (
                v_email.user_id,
                v_fields->>'title',
                (v_fields->>'start_datetime')::timestamptz,
                (v_fields->>'end_datetime')::timestamptz,
                COALESCE((v_fields->>'all_day')::boolean, false),
                v_fields->>'location',
                v_fields->>'description',
                COALESCE(v_fields->>'importance', 'action_required'),
                COALESCE(v_fields->>'status', 'pending_review'),
                v_fields->>'recurrence_rule',
                v_fields->>'google_calendar_event_id'
            ) RETURNING id INTO v_event_id;
            v_event_ids := v_event_ids || to_jsonb(v_event_id);
        ELSE
            v_event_id := (v_decision->>'event_id')::uuid;
            IF v_event_id IS NULL THEN
                RAISE EXCEPTION 'update decision requires event_id';
            END IF;
            PERFORM 1 FROM public.events
            WHERE id = v_event_id AND user_id = v_email.user_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'event % is not owned by email user', v_event_id;
            END IF;

            IF COALESCE((v_source->>'replace_pending_proposal')::boolean, false) THEN
                UPDATE public.event_sources
                SET is_undone = true
                WHERE event_id = v_event_id
                  AND source_type IN ('update', 'cancellation')
                  AND is_undone = false;
            END IF;

            UPDATE public.events
            SET title = CASE WHEN v_fields ? 'title' THEN v_fields->>'title' ELSE title END,
                start_datetime = CASE WHEN v_fields ? 'start_datetime' THEN (v_fields->>'start_datetime')::timestamptz ELSE start_datetime END,
                end_datetime = CASE WHEN v_fields ? 'end_datetime' THEN (v_fields->>'end_datetime')::timestamptz ELSE end_datetime END,
                all_day = CASE WHEN v_fields ? 'all_day' THEN (v_fields->>'all_day')::boolean ELSE all_day END,
                location = CASE WHEN v_fields ? 'location' THEN v_fields->>'location' ELSE location END,
                description = CASE WHEN v_fields ? 'description' THEN v_fields->>'description' ELSE description END,
                importance = CASE WHEN v_fields ? 'importance' THEN v_fields->>'importance' ELSE importance END,
                status = CASE WHEN v_fields ? 'status' THEN v_fields->>'status' ELSE status END,
                recurrence_rule = CASE WHEN v_fields ? 'recurrence_rule' THEN v_fields->>'recurrence_rule' ELSE recurrence_rule END,
                updated_at = now()
            WHERE id = v_event_id;
        END IF;

        IF v_source_origin = 'google_calendar' THEN
            INSERT INTO public.event_sources (
                event_id, source_origin, google_calendar_source_event_id,
                source_type, extracted_data, event_snapshot_before, change_set
            ) VALUES (
                v_event_id, v_source_origin, v_google_source_id, v_source_type,
                COALESCE(v_source->'extracted_data', '{}'::jsonb),
                v_source->'event_snapshot_before', v_source->'change_set'
            );
        ELSE
            INSERT INTO public.event_sources (
                event_id, email_id, source_origin, source_type,
                extracted_data, event_snapshot_before, change_set
            ) VALUES (
                v_event_id,
                COALESCE((v_source->>'email_id')::uuid, p_email_id),
                v_source_origin, v_source_type,
                COALESCE(v_source->'extracted_data', '{}'::jsonb),
                v_source->'event_snapshot_before', v_source->'change_set'
            )
            ON CONFLICT (event_id, email_id) WHERE source_origin = 'email' DO UPDATE
            SET source_type = EXCLUDED.source_type,
                extracted_data = EXCLUDED.extracted_data,
                event_snapshot_before = EXCLUDED.event_snapshot_before,
                change_set = EXCLUDED.change_set,
                is_undone = false;
        END IF;

        FOR v_extra IN
            SELECT value FROM jsonb_array_elements(COALESCE(v_source->'extra_sources', '[]'::jsonb))
        LOOP
            IF COALESCE(v_extra->>'source_origin', 'email') = 'google_calendar' THEN
                INSERT INTO public.event_sources (
                    event_id, source_origin, google_calendar_source_event_id,
                    source_type, extracted_data, event_snapshot_before, change_set
                ) VALUES (
                    v_event_id, 'google_calendar',
                    v_extra->>'google_calendar_source_event_id',
                    COALESCE(v_extra->>'source_type', v_source_type),
                    COALESCE(v_extra->'extracted_data', '{}'::jsonb),
                    v_extra->'event_snapshot_before', v_extra->'change_set'
                );
            ELSE
                INSERT INTO public.event_sources (
                    event_id, email_id, source_origin, source_type,
                    extracted_data, event_snapshot_before, change_set
                ) VALUES (
                    v_event_id, COALESCE((v_extra->>'email_id')::uuid, p_email_id),
                    'email', COALESCE(v_extra->>'source_type', v_source_type),
                    COALESCE(v_extra->'extracted_data', '{}'::jsonb),
                    v_extra->'event_snapshot_before', v_extra->'change_set'
                )
                ON CONFLICT (event_id, email_id) WHERE source_origin = 'email' DO UPDATE
                SET source_type = EXCLUDED.source_type,
                    extracted_data = EXCLUDED.extracted_data,
                    event_snapshot_before = EXCLUDED.event_snapshot_before,
                    change_set = EXCLUDED.change_set,
                    is_undone = false;
            END IF;
        END LOOP;

        v_applied := v_applied + 1;
    END LOOP;

    UPDATE public.emails
    SET processing_status = p_terminal,
        processing_error = NULL,
        processed_at = CASE WHEN p_terminal = 'processed' THEN now() ELSE processed_at END,
        locked_by = NULL,
        locked_until = NULL
    WHERE id = p_email_id;

    RETURN jsonb_build_object(
        'fenced', false,
        'applied', v_applied,
        'event_ids', v_event_ids
    );
END;
$$;

REVOKE ALL ON FUNCTION public.commit_email_extraction(uuid, text, bigint, jsonb, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.commit_email_extraction(uuid, text, bigint, jsonb, text) TO service_role;
COMMENT ON FUNCTION public.commit_email_extraction(uuid, text, bigint, jsonb, text)
    IS 'Atomically commit extracted-event decisions only while the worker still owns the email lease generation';
