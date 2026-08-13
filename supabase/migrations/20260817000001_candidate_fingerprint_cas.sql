-- P2: fence extracted-event decisions against the exact local-day candidate
-- band the resolver read.  The advisory key is held only during this short
-- commit transaction (never during extraction or LLM I/O); it makes the
-- fingerprint check a real CAS when two commits race on an empty band.

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
    v_actual_fingerprint text;
    v_window_start timestamptz;
    v_window_end timestamptz;
    v_index integer;
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

    -- Serialize only commits for the same user/day band.  Sorting the keys
    -- prevents deadlocks when one email contains events on multiple days.
    FOR v_decision IN
        SELECT value
        FROM jsonb_array_elements(COALESCE(p_decisions, '[]'::jsonb)) AS item(value)
        WHERE value->>'action' <> 'noop'
        ORDER BY value->>'window_start', value->>'window_end'
    LOOP
        IF v_decision->>'action' NOT IN ('create', 'update', 'noop') THEN
            RAISE EXCEPTION 'invalid extraction decision action: %', v_decision->>'action';
        END IF;
        IF v_decision->>'action' = 'noop' THEN
            CONTINUE;
        END IF;
        IF v_decision->>'window_start' IS NULL
           OR v_decision->>'window_end' IS NULL THEN
            RAISE EXCEPTION 'decision is missing candidate window';
        END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended(
            v_email.user_id::text || '|' || (v_decision->>'window_start') || '|' || (v_decision->>'window_end'),
            0
        ));
    END LOOP;

    -- Validate every decision before applying any one of them.  The canonical
    -- timestamp format is shared with resolution_fingerprint.py.
    IF jsonb_array_length(COALESCE(p_decisions, '[]'::jsonb)) > 0 THEN
        FOR v_index IN 0..jsonb_array_length(COALESCE(p_decisions, '[]'::jsonb)) - 1
        LOOP
        v_decision := p_decisions->v_index;
        v_action := v_decision->>'action';
        IF v_action NOT IN ('create', 'update', 'noop') THEN
            RAISE EXCEPTION 'invalid extraction decision action: %', v_action;
        END IF;
        IF v_action = 'noop' THEN
            CONTINUE;
        END IF;
        v_window_start := (v_decision->>'window_start')::timestamptz;
        v_window_end := (v_decision->>'window_end')::timestamptz;
        SELECT md5(COALESCE(string_agg(
            e.id::text || ':' || to_char(
                e.updated_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
            ),
            ',' ORDER BY e.id
        ), '')) INTO v_actual_fingerprint
        FROM public.events AS e
        WHERE e.user_id = v_email.user_id
          AND e.start_datetime >= v_window_start
          AND e.start_datetime < v_window_end;

        IF v_actual_fingerprint IS DISTINCT FROM v_decision->>'expected_fingerprint' THEN
            RETURN jsonb_build_object(
                'fenced', false,
                'conflict', true,
                'conflicting_indexes', jsonb_build_array(v_index)
            );
        END IF;
        END LOOP;
    END IF;

    FOR v_decision IN
        SELECT value FROM jsonb_array_elements(COALESCE(p_decisions, '[]'::jsonb))
    LOOP
        v_action := v_decision->>'action';
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
        'conflict', false,
        'applied', v_applied,
        'event_ids', v_event_ids
    );
END;
$$;

REVOKE ALL ON FUNCTION public.commit_email_extraction(uuid, text, bigint, jsonb, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.commit_email_extraction(uuid, text, bigint, jsonb, text) TO service_role;
COMMENT ON FUNCTION public.commit_email_extraction(uuid, text, bigint, jsonb, text)
    IS 'Atomically commit extracted-event decisions with lease and candidate fingerprint fences';
