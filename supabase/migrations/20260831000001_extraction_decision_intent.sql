-- The extraction commit must be told what to do with a change, not left to
-- infer it from a status field that means something else.
--
-- `commit_email_extraction` derived `v_auto_apply := v_review_status =
-- 'active'`, so one field answered two unrelated questions: "what lane is this
-- event in" and "should this change be applied without asking". For the
-- Changes lane those answers contradict each other by construction -- a pending
-- proposal *requires* events.review_status = 'active'
-- (enforce_event_change_proposal_invariant), which is exactly the value that
-- made v_auto_apply true. The caller could only reach the review path by
-- sending a review_status it knew to be false, and the RPC corrected it three
-- statements later with `IF NOT v_auto_apply THEN UPDATE events SET
-- review_status = 'active'`.
--
-- dd3b82e8 (#332) stopped sending that lie (`{"status": "pending_change"}` ->
-- `{}`), and `COALESCE(v_fields->>'review_status', ... ELSE 'active')` decoded
-- the resulting silence as "apply this and write it to the user's Google
-- Calendar". Every email-driven Changes-lane card has been silently
-- auto-applied since. No test caught it because none has ever executed this
-- function with a change_set: the unit tests stub the commit, and the proposal
-- integration tests INSERT proposal rows directly.
--
-- Two further consequences of the same overload:
--   * review_status 'rejected' and 'cancelled' had no encoding at all, so a
--     matched rejected event fell through to the propose-and-promote branch and
--     was resurrected -- violating review-queue-integrity.md 8.2 ("Record
--     matched source/outcome, remain rejected"), which queue_event_cancellation
--     already enforces and ingestion never learned.
--   * _enqueue_calendar_work promoted pending_review/rejected/cancelled to
--     'active' on every call, so review state -- which events.review_status is
--     supposed to own -- changed as a side effect of queueing work.
--
-- The decision envelope now carries an explicit `intent` describing what to do
-- with the change, orthogonal to `action` (create/update) and to
-- `fields.review_status` (which recovers its honest meaning). Both are
-- required: an absent or unrecognized intent raises, and so does an absent
-- review_status, so silence can no longer mean "write to their calendar".

-- 1. The queue helper stops writing the user's review decision.
--
-- events.review_status owns the user decision; a work-queue helper must not
-- mutate it. The promotion was relied on by exactly one caller
-- (set_event_review_status, which never set 'active' itself) and actively
-- undone by two others (undo_/unsync_event_and_enqueue_calendar_work, both of
-- which set 'pending_review' immediately after). Each caller now states its own
-- intent before enqueueing, and the helper fails closed on an event the user
-- has already declined.
CREATE OR REPLACE FUNCTION public._enqueue_calendar_work(
    p_event_id uuid, p_user_id uuid, p_action text, p_desired_event jsonb,
    p_expected_provider_revision text, p_force_overwrite boolean
) RETURNS public.calendar_work_items
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_event public.events; v_item public.calendar_work_items; v_generation bigint;
BEGIN
    IF p_action NOT IN ('upsert', 'cancel') THEN
        RAISE EXCEPTION 'invalid calendar work action %', p_action USING ERRCODE = '22023';
    END IF;
    IF p_action = 'upsert' AND p_desired_event IS NULL THEN
        RAISE EXCEPTION 'upsert calendar work requires desired_event' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_event FROM public.events
    WHERE id = p_event_id AND user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'event % is not owned by user %', p_event_id, p_user_id USING ERRCODE = '42501';
    END IF;
    -- A caller that legitimately revives a declined event sets review_status
    -- first; this runs in the same transaction and will see 'active'. An
    -- upsert against a still-rejected event is a bug, and says so.
    IF p_action = 'upsert' AND v_event.review_status IN ('rejected', 'cancelled') THEN
        RAISE EXCEPTION 'cannot queue calendar upsert for % event %', v_event.review_status, p_event_id
            USING ERRCODE = '22023';
    END IF;
    SELECT COALESCE(max(generation), 0) + 1 INTO v_generation
    FROM public.calendar_work_items WHERE event_id = p_event_id;
    UPDATE public.calendar_work_items
    SET status = 'superseded', updated_at = now(), completed_at = now()
    WHERE event_id = p_event_id AND status IN ('pending', 'processing');
    INSERT INTO public.calendar_work_items (
        event_id, user_id, action, generation, desired_event,
        provider_event_id, expected_provider_revision, force_overwrite,
        attempts, max_attempts
    ) VALUES (
        p_event_id, p_user_id, p_action, v_generation, p_desired_event,
        v_event.google_calendar_event_id, p_expected_provider_revision,
        COALESCE(p_force_overwrite, false), 0, 3
    ) RETURNING * INTO v_item;
    UPDATE public.events SET updated_at = now() WHERE id = p_event_id;
    RETURN v_item;
END;
$$;

REVOKE ALL ON FUNCTION public._enqueue_calendar_work(uuid, uuid, text, jsonb, text, boolean) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public._enqueue_calendar_work(uuid, uuid, text, jsonb, text, boolean) TO service_role;

-- 2. The one caller that depended on the promotion now performs it itself.
CREATE OR REPLACE FUNCTION public.set_event_review_status(
    p_event_id uuid, p_review_status text, p_user_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_event public.events;
    v_item public.calendar_work_items;
    v_user_id uuid;
BEGIN
    IF p_review_status NOT IN ('active', 'rejected') THEN
        RAISE EXCEPTION 'invalid event review status %', p_review_status USING ERRCODE = '22023';
    END IF;
    IF p_user_id IS NOT NULL
       AND auth.uid() IS DISTINCT FROM p_user_id
       AND auth.role() <> 'service_role' THEN
        RAISE EXCEPTION 'event % is not owned by the caller', p_event_id USING ERRCODE = '42501';
    END IF;
    v_user_id := COALESCE(p_user_id, auth.uid());
    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'authentication required' USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_event FROM public.events
    WHERE id = p_event_id AND user_id = v_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'event % is not owned by the caller', p_event_id USING ERRCODE = '42501';
    END IF;
    IF p_review_status = 'active' THEN
        -- Explicit, and ordered before the enqueue so the helper's guard sees
        -- the decision this call is making rather than the one it replaces.
        UPDATE public.events SET review_status = 'active', updated_at = now()
        WHERE id = p_event_id;
        v_item := public._enqueue_calendar_work(
            p_event_id, v_event.user_id, 'upsert',
            jsonb_build_object(
                'title', v_event.title, 'start_datetime', v_event.start_datetime,
                'end_datetime', v_event.end_datetime, 'all_day', v_event.all_day,
                'location', v_event.location, 'description', v_event.description,
                'importance', v_event.importance, 'source_attribution', v_event.source_attribution
            ), NULL, false);
    ELSE
        UPDATE public.events SET review_status = 'rejected', updated_at = now()
        WHERE id = p_event_id;
    END IF;
    RETURN jsonb_build_object(
        'event_id', p_event_id, 'review_status', p_review_status,
        'work_item_id', v_item.id, 'generation', v_item.generation
    );
END;
$$;

REVOKE ALL ON FUNCTION public.set_event_review_status(uuid, text, uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.set_event_review_status(uuid, text, uuid) TO authenticated, service_role;

-- 3. Automatic cancellation of a not-yet-approved event kept its behaviour,
-- which previously came from the helper's promotion: the event becomes active
-- so complete_calendar_work can transition it to 'cancelled' on delivery.
-- Rejected and already-cancelled events are refused/short-circuited as before.
CREATE OR REPLACE FUNCTION public.queue_event_cancellation(p_event_id uuid, p_user_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_event public.events; v_item public.calendar_work_items;
BEGIN
    SELECT * INTO v_event FROM public.events WHERE id = p_event_id AND user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'event % is not owned by user %', p_event_id, p_user_id; END IF;
    IF v_event.review_status = 'cancelled' THEN
        RETURN jsonb_build_object('event_id', p_event_id, 'status', 'cancelled', 'already_cancelled', true);
    END IF;
    IF v_event.review_status = 'rejected' OR EXISTS (
        SELECT 1 FROM public.calendar_work_items w
        WHERE w.event_id = p_event_id AND w.status = 'processing'
    ) THEN
        RAISE EXCEPTION 'event % cannot be cancelled in its current state', p_event_id;
    END IF;
    IF v_event.review_status = 'pending_review' THEN
        UPDATE public.events SET review_status = 'active', updated_at = now() WHERE id = p_event_id;
    END IF;
    v_item := public._enqueue_calendar_work(p_event_id, p_user_id, 'cancel', NULL, NULL, false);
    RETURN jsonb_build_object('event_id', p_event_id, 'status', 'cancel_queued',
        'work_item_id', v_item.id, 'generation', v_item.generation, 'already_cancelled', false);
END;
$$;

REVOKE ALL ON FUNCTION public.queue_event_cancellation(uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.queue_event_cancellation(uuid, uuid) TO service_role;

-- 4. The extraction commit is told the disposition of the change.
--
-- `intent` is orthogonal to `action` (create/update) and to
-- `fields.review_status` (the lane the event belongs in):
--
--   no_change    the decision carries no change_set (a new invitation)
--   apply        apply the change now (sender auto-approve, automatic
--                cancellation, or absorbing info into a not-yet-approved event)
--   review       hold the change for the user -- the Changes lane
--   record_only  record provenance and identity only; change nothing
--
-- Calendar delivery follows review_status, not intent: work is queued only for
-- an event that is 'active' and whose change is being applied. That is what
-- lets `apply` merge new information into a 'pending_review' event without
-- touching the user's calendar, and lets `review` leave an 'active' event
-- exactly where it is while its proposal waits.
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
                SELECT md5(COALESCE(string_agg(e.id::text || ':' || to_char(e.updated_at AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), ',' ORDER BY e.id), '')) INTO v_hint_fingerprint
                FROM public.events e WHERE e.user_id = v_email.user_id AND e.id IN (
                    SELECT DISTINCT h.event_id FROM public.event_identity_hints h
                    WHERE h.user_id = v_email.user_id AND format('%s|%s|%s', h.kind, h.value_hash, h.recurrence_id)
                        IN (SELECT value::text FROM jsonb_array_elements_text(v_decision->'hint_keys')));
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

REVOKE ALL ON FUNCTION public.commit_email_extraction(uuid, text, bigint, jsonb, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.commit_email_extraction(uuid, text, bigint, jsonb, text) TO service_role;

COMMENT ON FUNCTION public.commit_email_extraction(uuid, text, bigint, jsonb, text) IS
    'Fenced extraction commit. Every decision states an explicit intent (no_change/apply/review/record_only) and, except for record_only, an explicit review_status; neither has a default.';
