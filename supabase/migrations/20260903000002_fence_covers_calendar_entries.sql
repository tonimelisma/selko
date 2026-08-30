-- I3 (continued): extend the commit fence to cover mirrored calendar entries.
--
-- commit_email_extraction re-checks at write time that the rows a decision was
-- computed against have not changed since. Its hint fingerprint covered
-- public.events only. Now that a hint can name a calendar_entries row, a
-- concurrent mirror sync could change the matched entry between the decision and
-- the commit and the fence would not notice -- the exact race the
-- parallel-extraction plan closed for events.
--
-- Derived mechanically from 20260831000001, the current definition, with only
-- the fingerprint query replaced. The first attempt derived from
-- 20260830000002 instead and silently reverted the extraction-intent logic that
-- 20260831000001 had added; the integration tests caught it, which is what they
-- are for.

CREATE OR REPLACE FUNCTION public.commit_email_extraction(
    p_email_id uuid, p_worker_id text, p_generation bigint,
    p_decisions jsonb, p_terminal text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_email public.emails; v_decision jsonb; v_extra jsonb; v_hint jsonb;
    v_source jsonb; v_fields jsonb; v_action text; v_source_origin text;
    v_source_type text; v_event_id uuid; v_source_id uuid; v_google_source_id text;
    v_actual_fingerprint text; v_hint_fingerprint text; v_window_start timestamptz;
    v_window_end timestamptz; v_index integer; v_hint_kind text; v_hint_hash text;
    v_hint_recurrence text; v_hint_sequence integer; v_hint_dtstamp timestamptz;
    v_applied integer := 0; v_event_ids jsonb := '[]'::jsonb;
    v_change_set jsonb; v_snapshot jsonb; v_proposal_status text;
    v_review_status text; v_calendar_action text; v_intent text;
    v_has_change boolean; v_apply_fields boolean; v_enqueue boolean;
BEGIN
    IF p_terminal NOT IN ('processed', 'skipped', 'failed') THEN
        RAISE EXCEPTION 'invalid extraction terminal status: %', p_terminal;
    END IF;
    SELECT * INTO v_email FROM public.emails WHERE id = p_email_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'email % not found', p_email_id; END IF;
    IF v_email.locked_by IS DISTINCT FROM p_worker_id OR v_email.lock_generation IS DISTINCT FROM p_generation THEN
        RETURN jsonb_build_object('fenced', true, 'applied', 0);
    END IF;

    FOR v_decision IN SELECT value FROM jsonb_array_elements(COALESCE(p_decisions, '[]'::jsonb)) AS item(value)
        WHERE value->>'action' <> 'noop' ORDER BY value->>'window_start', value->>'window_end'
    LOOP
        IF v_decision->>'action' NOT IN ('create', 'update', 'noop')
           OR v_decision->>'window_start' IS NULL OR v_decision->>'window_end' IS NULL THEN
            RAISE EXCEPTION 'invalid extraction decision envelope';
        END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended(v_email.user_id::text || '|' ||
            (v_decision->>'window_start') || '|' || (v_decision->>'window_end'), 0));
        FOR v_hint IN SELECT value FROM jsonb_array_elements(COALESCE(v_decision->'hints', '[]'::jsonb)) AS item(value)
            ORDER BY value->>'kind', value->>'value_hash', value->>'recurrence_id'
        LOOP
            PERFORM pg_advisory_xact_lock(hashtextextended(v_email.user_id::text || '|hint|' ||
                (v_hint->>'kind') || '|' || (v_hint->>'value_hash') || '|' || COALESCE(v_hint->>'recurrence_id', ''), 0));
        END LOOP;
    END LOOP;

    IF jsonb_array_length(COALESCE(p_decisions, '[]'::jsonb)) > 0 THEN
        FOR v_index IN 0..jsonb_array_length(COALESCE(p_decisions, '[]'::jsonb)) - 1 LOOP
            v_decision := p_decisions->v_index;
            IF v_decision->>'action' = 'noop' THEN CONTINUE; END IF;
            v_window_start := (v_decision->>'window_start')::timestamptz;
            v_window_end := (v_decision->>'window_end')::timestamptz;
            SELECT md5(COALESCE(string_agg(e.id::text || ':' || to_char(e.updated_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), ',' ORDER BY e.id), '')) INTO v_actual_fingerprint
            FROM public.events e WHERE e.user_id = v_email.user_id
              AND e.start_datetime >= v_window_start AND e.start_datetime < v_window_end;
            IF v_actual_fingerprint IS DISTINCT FROM v_decision->>'expected_fingerprint' THEN
                RETURN jsonb_build_object('fenced', false, 'conflict', true, 'conflicting_indexes', jsonb_build_array(v_index));
            END IF;
            IF jsonb_array_length(COALESCE(v_decision->'hint_keys', '[]'::jsonb)) > 0 THEN
                -- The fingerprint spans both entities a hint can name. Covering
                -- events only would let a concurrent calendar mirror sync change
                -- the very rows the match was computed against, between the
                -- decision and this commit -- reintroducing the race P2 closed.
                SELECT md5(COALESCE(string_agg(src.key, ',' ORDER BY src.key), '')) INTO v_hint_fingerprint
                FROM (
                    SELECT e.id::text || ':' || to_char(e.updated_at AT TIME ZONE 'UTC',
                        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS key
                    FROM public.events e WHERE e.user_id = v_email.user_id AND e.id IN (
                        SELECT DISTINCT h.event_id FROM public.event_identity_hints h
                        WHERE h.user_id = v_email.user_id AND h.event_id IS NOT NULL
                          AND format('%s|%s|%s', h.kind, h.value_hash, h.recurrence_id)
                            IN (SELECT value::text FROM jsonb_array_elements_text(v_decision->'hint_keys')))
                    UNION ALL
                    SELECT c.id::text || ':' || to_char(c.updated_at AT TIME ZONE 'UTC',
                        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS key
                    FROM public.calendar_entries c WHERE c.user_id = v_email.user_id AND c.id IN (
                        SELECT DISTINCT h.calendar_entry_id FROM public.event_identity_hints h
                        WHERE h.user_id = v_email.user_id AND h.calendar_entry_id IS NOT NULL
                          AND format('%s|%s|%s', h.kind, h.value_hash, h.recurrence_id)
                            IN (SELECT value::text FROM jsonb_array_elements_text(v_decision->'hint_keys')))
                ) src;
                IF v_hint_fingerprint IS DISTINCT FROM v_decision->>'expected_hint_fingerprint' THEN
                    RETURN jsonb_build_object('fenced', false, 'conflict', true, 'conflicting_indexes', jsonb_build_array(v_index));
                END IF;
            END IF;
        END LOOP;
    END IF;

    FOR v_decision IN SELECT value FROM jsonb_array_elements(COALESCE(p_decisions, '[]'::jsonb)) AS item(value) LOOP
        v_action := v_decision->>'action'; IF v_action = 'noop' THEN CONTINUE; END IF;
        v_fields := COALESCE(v_decision->'fields', '{}'::jsonb);
        v_source := COALESCE(v_decision->'source', '{}'::jsonb);
        v_source_origin := COALESCE(v_source->>'source_origin', 'email');
        v_source_type := COALESCE(v_source->>'source_type', 'new_invitation');
        v_google_source_id := v_source->>'google_calendar_source_event_id';
        v_change_set := v_source->'change_set'; v_snapshot := v_source->'event_snapshot_before';
        v_has_change := jsonb_typeof(v_change_set) = 'object' AND v_change_set <> '{}'::jsonb
            AND jsonb_typeof(v_snapshot) = 'object' AND v_snapshot <> '{}'::jsonb;

        v_intent := v_decision->>'intent';
        IF v_intent IS NULL OR v_intent NOT IN ('no_change', 'apply', 'review', 'record_only') THEN
            RAISE EXCEPTION 'extraction decision requires a known intent (got %)',
                COALESCE(v_intent, '<missing>') USING ERRCODE = '22023';
        END IF;
        IF v_intent = 'no_change' AND v_has_change THEN
            RAISE EXCEPTION 'intent no_change cannot carry a change_set' USING ERRCODE = '22023';
        END IF;
        IF v_intent IN ('apply', 'review') AND NOT v_has_change THEN
            RAISE EXCEPTION 'intent % requires a change_set and snapshot', v_intent USING ERRCODE = '22023';
        END IF;

        -- record_only touches neither the event nor any proposal. It exists so
        -- that a later email about an event the user declined keeps its
        -- provenance and identity hints -- which is what keeps the match
        -- working, and therefore what keeps the decision terminal instead of
        -- letting the next email create a duplicate in the New lane.
        IF v_intent = 'record_only' THEN
            IF v_action <> 'update' THEN
                RAISE EXCEPTION 'intent record_only requires an update decision' USING ERRCODE = '22023';
            END IF;
            v_event_id := (v_decision->>'event_id')::uuid;
            IF v_event_id IS NULL THEN RAISE EXCEPTION 'update decision requires event_id'; END IF;
            PERFORM 1 FROM public.events WHERE id = v_event_id AND user_id = v_email.user_id FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'event % is not owned by email user', v_event_id; END IF;
            v_review_status := NULL; v_apply_fields := false; v_enqueue := false;
        ELSE
            -- No COALESCE. An absent review_status used to mean 'active', which
            -- made silence the most destructive available reading.
            v_review_status := v_fields->>'review_status';
            IF v_review_status IS NULL THEN
                RAISE EXCEPTION 'extraction decision requires an explicit review_status' USING ERRCODE = '22023';
            END IF;
            IF v_review_status NOT IN ('pending_review', 'active', 'rejected', 'cancelled') THEN
                RAISE EXCEPTION 'invalid extraction review status %', v_review_status USING ERRCODE = '22023';
            END IF;
            IF v_intent = 'review' AND v_review_status <> 'active' THEN
                RAISE EXCEPTION 'a change held for review requires review_status active, got %',
                    v_review_status USING ERRCODE = '22023';
            END IF;
            v_calendar_action := COALESCE(v_fields->>'calendar_action', 'upsert');
            IF v_calendar_action NOT IN ('upsert', 'cancel') THEN
                RAISE EXCEPTION 'invalid extraction calendar action %', v_calendar_action USING ERRCODE = '22023';
            END IF;
            v_apply_fields := v_intent IN ('no_change', 'apply');
            v_enqueue := v_review_status = 'active' AND v_apply_fields;

            IF v_action = 'create' THEN
                INSERT INTO public.events (
                    user_id, title, start_datetime, end_datetime, all_day, location, description,
                    importance, review_status, recurrence_rule, google_calendar_event_id
                ) VALUES (
                    v_email.user_id, v_fields->>'title', (v_fields->>'start_datetime')::timestamptz,
                    (v_fields->>'end_datetime')::timestamptz, COALESCE((v_fields->>'all_day')::boolean, false),
                    v_fields->>'location', v_fields->>'description', COALESCE(v_fields->>'importance', 'action_required'),
                    v_review_status, v_fields->>'recurrence_rule', v_fields->>'google_calendar_event_id'
                ) RETURNING id INTO v_event_id;
                v_event_ids := v_event_ids || to_jsonb(v_event_id);
            ELSE
                v_event_id := (v_decision->>'event_id')::uuid;
                IF v_event_id IS NULL THEN RAISE EXCEPTION 'update decision requires event_id'; END IF;
                PERFORM 1 FROM public.events WHERE id = v_event_id AND user_id = v_email.user_id FOR UPDATE;
                IF NOT FOUND THEN RAISE EXCEPTION 'event % is not owned by email user', v_event_id; END IF;
                IF v_apply_fields THEN
                    UPDATE public.events SET
                        title = CASE WHEN v_fields ? 'title' THEN v_fields->>'title' ELSE title END,
                        start_datetime = CASE WHEN v_fields ? 'start_datetime' THEN (v_fields->>'start_datetime')::timestamptz ELSE start_datetime END,
                        end_datetime = CASE WHEN v_fields ? 'end_datetime' THEN (v_fields->>'end_datetime')::timestamptz ELSE end_datetime END,
                        all_day = CASE WHEN v_fields ? 'all_day' THEN (v_fields->>'all_day')::boolean ELSE all_day END,
                        location = CASE WHEN v_fields ? 'location' THEN v_fields->>'location' ELSE location END,
                        description = CASE WHEN v_fields ? 'description' THEN v_fields->>'description' ELSE description END,
                        importance = CASE WHEN v_fields ? 'importance' THEN v_fields->>'importance' ELSE importance END,
                        review_status = v_review_status,
                        recurrence_rule = CASE WHEN v_fields ? 'recurrence_rule' THEN v_fields->>'recurrence_rule' ELSE recurrence_rule END,
                        updated_at = now() WHERE id = v_event_id;
                ELSE
                    -- intent 'review': the proposal owns the change. The event
                    -- keeps every current value and only its lane is asserted.
                    UPDATE public.events SET review_status = v_review_status, updated_at = now()
                    WHERE id = v_event_id;
                END IF;
            END IF;
        END IF;

        IF v_source_origin = 'google_calendar' THEN
            INSERT INTO public.event_sources(event_id, source_origin, google_calendar_source_event_id, source_type, extracted_data)
            VALUES(v_event_id, v_source_origin, v_google_source_id, v_source_type, COALESCE(v_source->'extracted_data', '{}'::jsonb))
            RETURNING id INTO v_source_id;
        ELSE
            INSERT INTO public.event_sources(event_id, email_id, source_origin, source_type, extracted_data)
            VALUES(v_event_id, COALESCE((v_source->>'email_id')::uuid, p_email_id), v_source_origin, v_source_type,
                COALESCE(v_source->'extracted_data', '{}'::jsonb))
            ON CONFLICT (event_id, email_id) WHERE source_origin = 'email' DO UPDATE SET
                source_type = EXCLUDED.source_type, extracted_data = EXCLUDED.extracted_data
            RETURNING id INTO v_source_id;
        END IF;

        FOR v_extra IN SELECT value FROM jsonb_array_elements(COALESCE(v_source->'extra_sources', '[]'::jsonb)) AS item(value) LOOP
            IF COALESCE(v_extra->>'source_origin', 'email') = 'google_calendar' THEN
                INSERT INTO public.event_sources(event_id, source_origin, google_calendar_source_event_id, source_type, extracted_data)
                VALUES(v_event_id, 'google_calendar', v_extra->>'google_calendar_source_event_id',
                    COALESCE(v_extra->>'source_type', v_source_type), COALESCE(v_extra->'extracted_data', '{}'::jsonb));
            END IF;
        END LOOP;

        IF v_intent IN ('apply', 'review') THEN
            UPDATE public.event_change_proposals SET status = 'superseded', resolution_reason = 'superseded_by_newer_proposal',
                resolved_at = now(), updated_at = now() WHERE event_id = v_event_id AND status = 'pending' AND source_id <> v_source_id;
            v_proposal_status := CASE WHEN v_intent = 'apply' THEN 'applied' ELSE 'pending' END;
            INSERT INTO public.event_change_proposals(event_id, user_id, source_id, kind, status, change_set, event_snapshot_before, resolution_reason)
            VALUES(v_event_id, v_email.user_id, v_source_id,
                CASE WHEN v_source_type = 'cancellation' THEN 'cancellation' ELSE 'material_update' END,
                v_proposal_status, v_change_set, v_snapshot,
                CASE WHEN v_intent = 'apply' THEN 'automatic_apply' ELSE NULL END)
            ON CONFLICT (source_id) DO UPDATE SET status = EXCLUDED.status, change_set = EXCLUDED.change_set,
                event_snapshot_before = EXCLUDED.event_snapshot_before, resolution_reason = EXCLUDED.resolution_reason,
                resolved_at = CASE WHEN EXCLUDED.status = 'pending' THEN NULL ELSE now() END, updated_at = now();
        END IF;

        IF v_enqueue THEN
            PERFORM public._enqueue_calendar_work(
                v_event_id, v_email.user_id, v_calendar_action,
                CASE WHEN v_calendar_action = 'cancel' THEN NULL ELSE jsonb_build_object(
                    'title', v_fields->>'title', 'start_datetime', v_fields->>'start_datetime',
                    'end_datetime', v_fields->>'end_datetime', 'all_day', COALESCE((v_fields->>'all_day')::boolean, false),
                    'location', v_fields->>'location', 'description', v_fields->>'description',
                    'importance', COALESCE(v_fields->>'importance', 'action_required')
                ) END, NULL, false
            );
        END IF;

        FOR v_hint IN SELECT value FROM jsonb_array_elements(COALESCE(v_decision->'hints', '[]'::jsonb)) AS item(value) LOOP
            v_hint_kind := v_hint->>'kind'; v_hint_hash := v_hint->>'value_hash';
            v_hint_recurrence := COALESCE(v_hint->>'recurrence_id', '');
            IF v_hint_kind NOT IN ('ical_uid', 'provider_thread', 'join_url', 'management_url')
               OR v_hint->>'strength' NOT IN ('authoritative', 'supporting') OR NULLIF(v_hint_hash, '') IS NULL THEN
                RAISE EXCEPTION 'invalid identity hint';
            END IF;
            v_hint_sequence := COALESCE(NULLIF(v_hint->>'sequence', '')::integer, 0);
            v_hint_dtstamp := NULLIF(v_hint->>'dtstamp', '')::timestamptz;
            INSERT INTO public.event_identity_hints(user_id, event_id, source_email_id, kind, value_hash, recurrence_id, strength, sequence, dtstamp)
            VALUES(v_email.user_id, v_event_id, p_email_id, v_hint_kind, v_hint_hash, v_hint_recurrence,
                v_hint->>'strength', v_hint_sequence, v_hint_dtstamp)
            ON CONFLICT (event_id, kind, value_hash, recurrence_id) DO UPDATE SET
                source_email_id = EXCLUDED.source_email_id, strength = EXCLUDED.strength,
                sequence = CASE WHEN EXCLUDED.kind = 'ical_uid' AND EXCLUDED.sequence >= event_identity_hints.sequence
                    THEN EXCLUDED.sequence ELSE event_identity_hints.sequence END,
                dtstamp = CASE WHEN EXCLUDED.kind = 'ical_uid' AND EXCLUDED.sequence >= event_identity_hints.sequence
                    THEN EXCLUDED.dtstamp ELSE event_identity_hints.dtstamp END;
        END LOOP;
        v_applied := v_applied + 1;
    END LOOP;
    UPDATE public.emails SET processing_status = p_terminal, processing_error = NULL,
        processed_at = CASE WHEN p_terminal = 'processed' THEN now() ELSE processed_at END,
        locked_by = NULL, locked_until = NULL WHERE id = p_email_id;
    RETURN jsonb_build_object('fenced', false, 'conflict', false, 'applied', v_applied, 'event_ids', v_event_ids);
END;
$$;
