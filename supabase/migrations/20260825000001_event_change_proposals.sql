-- S3: make event change proposals first-class state.
-- event_sources remains a deployed-client compatibility projection.  It is no
-- longer the owner of proposal lifecycle or review selection.

CREATE TABLE public.event_change_proposals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id uuid NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    source_id uuid NOT NULL UNIQUE REFERENCES public.event_sources(id) ON DELETE RESTRICT,
    kind text NOT NULL CHECK (kind IN ('material_update', 'cancellation')),
    status text NOT NULL CHECK (status IN ('pending', 'applied', 'rejected', 'superseded', 'closed_legacy')),
    change_set jsonb NOT NULL CHECK (jsonb_typeof(change_set) = 'object' AND change_set <> '{}'::jsonb),
    event_snapshot_before jsonb NOT NULL CHECK (jsonb_typeof(event_snapshot_before) = 'object' AND event_snapshot_before <> '{}'::jsonb),
    resolution_reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT event_change_proposals_source_owner_check CHECK (user_id IS NOT NULL)
);

ALTER TABLE public.event_change_proposals ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.event_change_proposals FROM PUBLIC, anon;
GRANT SELECT ON TABLE public.event_change_proposals TO authenticated;
GRANT ALL ON TABLE public.event_change_proposals TO service_role;
CREATE POLICY event_change_proposals_owner_select
    ON public.event_change_proposals FOR SELECT TO authenticated
    USING (user_id = auth.uid());
CREATE INDEX event_change_proposals_event_created_idx
    ON public.event_change_proposals (event_id, created_at DESC, id DESC);
CREATE UNIQUE INDEX event_change_proposals_one_pending_per_event
    ON public.event_change_proposals (event_id)
    WHERE status = 'pending';

-- Backfill only structurally complete proposals.  A pending-change event with
-- anything other than exactly one complete active candidate aborts the whole
-- migration and reports identifiers/counts only; proposal content is never
-- printed or guessed.
DO $$
DECLARE
    v_event record;
    v_total integer;
    v_complete integer;
BEGIN
    FOR v_event IN
        SELECT id FROM public.events WHERE status = 'pending_change' ORDER BY id
    LOOP
        SELECT count(*), count(*) FILTER (
            WHERE jsonb_typeof(s.change_set) = 'object'
              AND s.change_set <> '{}'::jsonb
              AND jsonb_typeof(s.event_snapshot_before) = 'object'
              AND s.event_snapshot_before <> '{}'::jsonb
        )
        INTO v_total, v_complete
        FROM public.event_sources AS s
        WHERE s.event_id = v_event.id
          AND s.source_type IN ('update', 'cancellation')
          AND s.is_undone = false;
        IF v_total <> 1 OR v_complete <> 1 THEN
            RAISE EXCEPTION 'event_change_proposals backfill ambiguous event_id=% total=% complete=%',
                v_event.id, v_total, v_complete;
        END IF;
    END LOOP;
END;
$$;

INSERT INTO public.event_change_proposals (
    event_id, user_id, source_id, kind, status, change_set,
    event_snapshot_before, resolution_reason
)
SELECT
    s.event_id,
    e.user_id,
    s.id,
    CASE WHEN s.source_type = 'cancellation' THEN 'cancellation' ELSE 'material_update' END,
    CASE WHEN e.status = 'pending_change' THEN 'pending' ELSE 'applied' END,
    s.change_set,
    s.event_snapshot_before,
    CASE WHEN e.status = 'pending_change' THEN NULL ELSE 'legacy_backfill_applied' END
FROM public.event_sources AS s
JOIN public.events AS e ON e.id = s.event_id
WHERE s.source_type IN ('update', 'cancellation')
  AND s.is_undone = false
  AND jsonb_typeof(s.change_set) = 'object' AND s.change_set <> '{}'::jsonb
  AND jsonb_typeof(s.event_snapshot_before) = 'object' AND s.event_snapshot_before <> '{}'::jsonb;

INSERT INTO public.event_change_proposals (
    event_id, user_id, source_id, kind, status, change_set,
    event_snapshot_before, resolution_reason
)
SELECT
    s.event_id,
    e.user_id,
    s.id,
    CASE WHEN s.source_type = 'cancellation' THEN 'cancellation' ELSE 'material_update' END,
    'closed_legacy',
    s.change_set,
    s.event_snapshot_before,
    'legacy_state_ambiguous'
FROM public.event_sources AS s
JOIN public.events AS e ON e.id = s.event_id
WHERE s.source_type IN ('update', 'cancellation')
  AND s.is_undone = true
  AND jsonb_typeof(s.change_set) = 'object' AND s.change_set <> '{}'::jsonb
  AND jsonb_typeof(s.event_snapshot_before) = 'object' AND s.event_snapshot_before <> '{}'::jsonb;

-- Existing clients may still read these columns.  They may no longer mutate
-- sources directly; only service-owned RPCs can write the compatibility rows.
DROP POLICY IF EXISTS "Users can manage own event_sources" ON public.event_sources;
CREATE POLICY event_sources_owner_select
    ON public.event_sources FOR SELECT TO authenticated
    USING (EXISTS (
        SELECT 1 FROM public.events
        WHERE events.id = event_sources.event_id
          AND events.user_id = auth.uid()
    ));
REVOKE INSERT, UPDATE, DELETE ON TABLE public.event_sources FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.event_sources TO authenticated;

CREATE OR REPLACE FUNCTION public.event_change_proposal_hash(p_proposal public.event_change_proposals)
RETURNS text
LANGUAGE sql IMMUTABLE
SET search_path = public, extensions AS $$
    SELECT encode(extensions.digest(convert_to(
        jsonb_build_object(
            'id', p_proposal.id,
            'event_id', p_proposal.event_id,
            'user_id', p_proposal.user_id,
            'source_id', p_proposal.source_id,
            'kind', p_proposal.kind,
            'status', p_proposal.status,
            'change_set', p_proposal.change_set,
            'event_snapshot_before', p_proposal.event_snapshot_before,
            'resolution_reason', p_proposal.resolution_reason,
            'created_at', p_proposal.created_at,
            'resolved_at', p_proposal.resolved_at,
            'updated_at', p_proposal.updated_at
        )::text, 'UTF8'), 'sha256'), 'hex');
$$;

CREATE OR REPLACE FUNCTION public.mirror_event_source_proposal()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_event public.events;
    v_status text;
    v_kind text;
BEGIN
    IF NEW.source_type NOT IN ('update', 'cancellation')
       OR jsonb_typeof(NEW.change_set) <> 'object'
       OR NEW.change_set = '{}'::jsonb
       OR jsonb_typeof(NEW.event_snapshot_before) <> 'object'
       OR NEW.event_snapshot_before = '{}'::jsonb THEN
        RETURN NEW;
    END IF;

    SELECT * INTO v_event FROM public.events WHERE id = NEW.event_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'event % not found for proposal source', NEW.event_id;
    END IF;
    v_kind := CASE WHEN NEW.source_type = 'cancellation' THEN 'cancellation' ELSE 'material_update' END;

    IF NEW.is_undone THEN
        UPDATE public.event_change_proposals
        SET status = CASE WHEN status = 'pending' THEN 'rejected' ELSE status END,
            resolution_reason = COALESCE(resolution_reason, 'legacy_source_undone'),
            resolved_at = COALESCE(resolved_at, now()),
            updated_at = now()
        WHERE source_id = NEW.id;
        RETURN NEW;
    END IF;

    UPDATE public.event_change_proposals
    SET status = 'superseded', resolution_reason = 'superseded_by_newer_proposal',
        resolved_at = now(), updated_at = now()
    WHERE event_id = NEW.event_id AND status = 'pending' AND source_id <> NEW.id;

    INSERT INTO public.event_change_proposals (
        event_id, user_id, source_id, kind, status, change_set,
        event_snapshot_before, resolution_reason
    ) VALUES (
        NEW.event_id, v_event.user_id, NEW.id, v_kind,
        CASE WHEN v_event.status = 'pending_change' THEN 'pending' ELSE 'applied' END,
        NEW.change_set, NEW.event_snapshot_before,
        CASE WHEN v_event.status = 'pending_change' THEN NULL ELSE 'legacy_source_mirror' END
    )
    ON CONFLICT (source_id) DO UPDATE SET
        kind = EXCLUDED.kind,
        change_set = EXCLUDED.change_set,
        event_snapshot_before = EXCLUDED.event_snapshot_before,
        updated_at = now();
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.mirror_event_source_proposal() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.mirror_event_source_proposal() TO service_role;
DROP TRIGGER IF EXISTS event_sources_proposal_mirror ON public.event_sources;
CREATE TRIGGER event_sources_proposal_mirror
    AFTER INSERT OR UPDATE OF is_undone, change_set, event_snapshot_before
    ON public.event_sources
    FOR EACH ROW EXECUTE FUNCTION public.mirror_event_source_proposal();

CREATE OR REPLACE FUNCTION public.enforce_event_change_proposal_invariant()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_event_id uuid;
    v_pending integer;
    v_active integer;
BEGIN
    IF TG_TABLE_NAME = 'events' THEN
        v_event_id := COALESCE(NEW.id, OLD.id);
    ELSIF TG_TABLE_NAME = 'event_sources' THEN
        v_event_id := COALESCE(NEW.event_id, OLD.event_id);
    ELSE
        v_event_id := COALESCE(NEW.event_id, OLD.event_id);
    END IF;

    SELECT count(*) FILTER (WHERE status = 'pending'),
           count(*) FILTER (WHERE status = 'pending' AND kind IN ('material_update', 'cancellation'))
    INTO v_pending, v_active
    FROM public.event_change_proposals
    WHERE event_id = v_event_id;

    IF EXISTS (SELECT 1 FROM public.events WHERE id = v_event_id AND status = 'pending_change')
       AND v_pending <> 1 THEN
        RAISE EXCEPTION 'event % requires exactly one pending change proposal (found %)', v_event_id, v_pending
            USING ERRCODE = '23514';
    END IF;
    IF v_pending > 0 AND NOT EXISTS (
        SELECT 1 FROM public.events
        WHERE id = v_event_id AND review_status = 'active'
    ) THEN
        RAISE EXCEPTION 'pending proposal event % must have active review status', v_event_id
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.event_change_proposals p
        JOIN public.events e ON e.id = p.event_id
        JOIN public.event_sources s ON s.id = p.source_id
        WHERE p.event_id = v_event_id
          AND p.status = 'pending'
          AND (p.user_id IS DISTINCT FROM e.user_id OR s.event_id IS DISTINCT FROM p.event_id
               OR jsonb_typeof(p.change_set) <> 'object' OR p.change_set = '{}'::jsonb
               OR jsonb_typeof(p.event_snapshot_before) <> 'object'
               OR p.event_snapshot_before = '{}'::jsonb)
    ) THEN
        RAISE EXCEPTION 'proposal ownership or payload invariant failed for event %', v_event_id
            USING ERRCODE = '23514';
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;

REVOKE ALL ON FUNCTION public.enforce_event_change_proposal_invariant() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.enforce_event_change_proposal_invariant() TO service_role;
DROP TRIGGER IF EXISTS events_pending_change_proposal_check ON public.events;
DROP TRIGGER IF EXISTS event_sources_pending_change_proposal_check ON public.event_sources;
DROP FUNCTION IF EXISTS public.enforce_pending_change_proposal();
DROP TRIGGER IF EXISTS event_change_proposals_pending_change_check ON public.event_change_proposals;
CREATE CONSTRAINT TRIGGER events_change_proposal_invariant
    AFTER INSERT OR UPDATE ON public.events DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION public.enforce_event_change_proposal_invariant();
CREATE CONSTRAINT TRIGGER event_sources_change_proposal_invariant
    AFTER INSERT OR UPDATE OR DELETE ON public.event_sources DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION public.enforce_event_change_proposal_invariant();
CREATE CONSTRAINT TRIGGER event_change_proposals_invariant
    AFTER INSERT OR UPDATE OR DELETE ON public.event_change_proposals DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION public.enforce_event_change_proposal_invariant();

CREATE OR REPLACE FUNCTION public._lock_owned_pending_proposal(
    p_event_id uuid, p_user_id uuid, p_proposal_id uuid, p_expected_hash text
) RETURNS public.event_change_proposals
LANGUAGE plpgsql SET search_path = public, extensions AS $$
DECLARE
    v_proposal public.event_change_proposals;
BEGIN
    SELECT p.* INTO v_proposal
    FROM public.event_change_proposals p
    JOIN public.events e ON e.id = p.event_id
    WHERE p.id = p_proposal_id AND p.event_id = p_event_id AND p.user_id = p_user_id
    FOR UPDATE OF p, e;
    IF NOT FOUND OR v_proposal.status <> 'pending' THEN
        RAISE EXCEPTION 'proposal % is not an owned pending proposal', p_proposal_id USING ERRCODE = 'P0001';
    END IF;
    IF p_expected_hash IS NOT NULL AND public.event_change_proposal_hash(v_proposal) <> p_expected_hash THEN
        RAISE EXCEPTION 'proposal % changed before transition', p_proposal_id USING ERRCODE = '40001';
    END IF;
    RETURN v_proposal;
END;
$$;

CREATE OR REPLACE FUNCTION public.apply_event_change_proposal(
    p_event_id uuid, p_user_id uuid, p_proposal_id uuid, p_expected_hash text,
    p_title text, p_start_datetime timestamptz, p_end_datetime timestamptz,
    p_all_day boolean, p_location text, p_description text, p_importance text,
    p_next_status text, p_calendar_sync_action text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_event public.events; v_proposal public.event_change_proposals;
BEGIN
    SELECT * INTO v_event FROM public.events WHERE id = p_event_id AND user_id = p_user_id FOR UPDATE;
    IF NOT FOUND OR v_event.status <> 'pending_change' THEN
        RAISE EXCEPTION 'event % is not an owned pending_change event', p_event_id;
    END IF;
    v_proposal := public._lock_owned_pending_proposal(p_event_id, p_user_id, p_proposal_id, p_expected_hash);
    IF p_next_status NOT IN ('approved', 'cancel_queued', 'cancelled') OR p_calendar_sync_action NOT IN ('upsert', 'cancel') THEN
        RAISE EXCEPTION 'invalid proposal application state' USING ERRCODE = '22023';
    END IF;
    UPDATE public.events SET title = p_title, start_datetime = p_start_datetime,
        end_datetime = p_end_datetime, all_day = p_all_day, location = p_location,
        description = p_description, importance = p_importance, status = p_next_status,
        calendar_sync_action = p_calendar_sync_action, sync_attempts = 0, updated_at = now()
    WHERE id = p_event_id;
    UPDATE public.event_change_proposals
    SET status = 'applied', resolution_reason = 'user_applied', resolved_at = now(), updated_at = now()
    WHERE id = v_proposal.id;
    UPDATE public.event_sources SET is_undone = false
    WHERE id = v_proposal.source_id;
    RETURN jsonb_build_object('event_id', p_event_id, 'proposal_id', v_proposal.id, 'status', p_next_status);
END;
$$;

CREATE OR REPLACE FUNCTION public.reject_event_change_proposal(
    p_event_id uuid, p_user_id uuid, p_proposal_id uuid, p_expected_hash text,
    p_delete_event boolean, p_restore_status text, p_title text,
    p_start_datetime timestamptz, p_end_datetime timestamptz, p_all_day boolean,
    p_location text, p_description text, p_importance text, p_resolution_reason text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_event public.events; v_proposal public.event_change_proposals;
BEGIN
    SELECT * INTO v_event FROM public.events WHERE id = p_event_id AND user_id = p_user_id FOR UPDATE;
    IF NOT FOUND OR v_event.status <> 'pending_change' THEN
        RAISE EXCEPTION 'event % is not an owned pending_change event', p_event_id;
    END IF;
    v_proposal := public._lock_owned_pending_proposal(p_event_id, p_user_id, p_proposal_id, p_expected_hash);
    IF p_resolution_reason IS NULL OR p_resolution_reason NOT IN ('user_rejected', 'repair_operator') THEN
        RAISE EXCEPTION 'invalid proposal rejection reason' USING ERRCODE = '22023';
    END IF;
    IF p_delete_event THEN
        IF v_event.google_calendar_event_id IS NULL OR v_event.synced_at IS NOT NULL THEN
            RAISE EXCEPTION 'event % is not an unsynced calendar-only proposal';
        END IF;
        DELETE FROM public.events WHERE id = p_event_id;
        RETURN jsonb_build_object('event_id', p_event_id, 'proposal_id', v_proposal.id, 'status', 'deleted');
    END IF;
    IF p_restore_status NOT IN ('pending_review', 'approved', 'synced', 'sync_failed', 'rejected', 'cancelled') THEN
        RAISE EXCEPTION 'invalid restored status %', p_restore_status USING ERRCODE = '22023';
    END IF;
    UPDATE public.event_change_proposals SET status = 'rejected', resolution_reason = p_resolution_reason,
        resolved_at = now(), updated_at = now() WHERE id = v_proposal.id;
    UPDATE public.event_sources SET is_undone = true WHERE id = v_proposal.source_id;
    UPDATE public.events SET status = p_restore_status, title = p_title,
        start_datetime = p_start_datetime, end_datetime = p_end_datetime, all_day = p_all_day,
        location = p_location, description = p_description, importance = p_importance, updated_at = now()
    WHERE id = p_event_id;
    RETURN jsonb_build_object('event_id', p_event_id, 'proposal_id', v_proposal.id, 'status', p_restore_status);
END;
$$;

CREATE OR REPLACE FUNCTION public.reopen_event_change_proposal(
    p_event_id uuid, p_user_id uuid, p_proposal_id uuid, p_expected_hash text,
    p_action text DEFAULT NULL, p_desired_event jsonb DEFAULT NULL,
    p_expected_provider_revision text DEFAULT NULL,
    p_force_overwrite boolean DEFAULT false
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_event public.events; v_proposal public.event_change_proposals; v_item jsonb;
BEGIN
    SELECT * INTO v_event FROM public.events WHERE id = p_event_id AND user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'event % is not owned', p_event_id; END IF;
    SELECT p.* INTO v_proposal FROM public.event_change_proposals p
    WHERE p.id = p_proposal_id AND p.event_id = p_event_id AND p.user_id = p_user_id FOR UPDATE;
    IF NOT FOUND OR v_proposal.status <> 'applied' THEN
        RAISE EXCEPTION 'proposal % is not an applied proposal', p_proposal_id;
    END IF;
    IF p_expected_hash IS NOT NULL AND public.event_change_proposal_hash(v_proposal) <> p_expected_hash THEN
        RAISE EXCEPTION 'proposal % changed before reopen', p_proposal_id USING ERRCODE = '40001';
    END IF;
    IF p_action IS NOT NULL AND p_action NOT IN ('upsert', 'cancel') THEN
        RAISE EXCEPTION 'invalid proposal reopen action %', p_action USING ERRCODE = '22023';
    END IF;
    UPDATE public.event_change_proposals SET status = 'pending', resolution_reason = NULL,
        resolved_at = NULL, updated_at = now() WHERE id = v_proposal.id;
    UPDATE public.events SET title = v_proposal.event_snapshot_before->>'title',
        start_datetime = (v_proposal.event_snapshot_before->>'start_datetime')::timestamptz,
        end_datetime = (v_proposal.event_snapshot_before->>'end_datetime')::timestamptz,
        all_day = COALESCE((v_proposal.event_snapshot_before->>'all_day')::boolean, false),
        location = v_proposal.event_snapshot_before->>'location',
        description = v_proposal.event_snapshot_before->>'description',
        importance = COALESCE(v_proposal.event_snapshot_before->>'importance', importance),
        status = 'pending_change', review_status = 'active', updated_at = now()
    WHERE id = p_event_id;
    IF p_action IS NOT NULL THEN
        v_item := to_jsonb(public._enqueue_calendar_work(
            p_event_id, p_user_id, p_action, p_desired_event,
            p_expected_provider_revision, p_force_overwrite, 'pending_change'
        ));
    END IF;
    RETURN jsonb_build_object('event_id', p_event_id, 'proposal_id', v_proposal.id, 'status', 'pending_change', 'calendar_work', v_item);
END;
$$;

CREATE OR REPLACE FUNCTION public.resolve_event_change_proposal(
    p_event_id uuid, p_user_id uuid, p_proposal_id uuid,
    p_expected_hash text, p_resolution_reason text
) RETURNS jsonb
LANGUAGE plpgsql SET search_path = public, extensions AS $$
DECLARE v_proposal public.event_change_proposals;
BEGIN
    SELECT p.* INTO v_proposal FROM public.event_change_proposals p
    JOIN public.events e ON e.id = p.event_id
    WHERE p.id = p_proposal_id AND p.event_id = p_event_id AND p.user_id = p_user_id
    FOR UPDATE OF p, e;
    IF NOT FOUND OR v_proposal.status <> 'closed_legacy' THEN
        RAISE EXCEPTION 'proposal % is not an owned closed legacy proposal', p_proposal_id;
    END IF;
    IF p_expected_hash IS NOT NULL AND public.event_change_proposal_hash(v_proposal) <> p_expected_hash THEN
        RAISE EXCEPTION 'proposal % changed before resolution', p_proposal_id USING ERRCODE = '40001';
    END IF;
    IF p_resolution_reason NOT IN ('historical_proposal_cleanup', 'operator_confirmed_rejection') THEN
        RAISE EXCEPTION 'invalid proposal resolution reason' USING ERRCODE = '22023';
    END IF;
    UPDATE public.event_change_proposals
    SET status = 'rejected', resolution_reason = p_resolution_reason,
        resolved_at = now(), updated_at = now()
    WHERE id = v_proposal.id;
    RETURN jsonb_build_object('event_id', p_event_id, 'proposal_id', v_proposal.id, 'status', 'rejected');
END;
$$;

-- Compatibility wrappers keep already-deployed callers working during S3/S4;
-- they resolve a source id to its typed proposal but do not read a source as
-- the authority.
CREATE OR REPLACE FUNCTION public.apply_pending_event_change(
    p_event_id uuid, p_user_id uuid, p_source_id uuid, p_title text,
    p_start_datetime timestamptz, p_end_datetime timestamptz, p_all_day boolean,
    p_location text, p_description text, p_importance text, p_next_status text,
    p_calendar_sync_action text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_proposal uuid;
BEGIN
    SELECT id INTO v_proposal FROM public.event_change_proposals
    WHERE event_id = p_event_id AND source_id = p_source_id;
    IF v_proposal IS NULL THEN RAISE EXCEPTION 'no proposal for source %', p_source_id; END IF;
    RETURN public.apply_event_change_proposal(p_event_id, p_user_id, v_proposal, NULL,
        p_title, p_start_datetime, p_end_datetime, p_all_day, p_location, p_description,
        p_importance, p_next_status, p_calendar_sync_action);
END;
$$;

CREATE OR REPLACE FUNCTION public.reject_pending_event_change(
    p_event_id uuid, p_user_id uuid, p_source_id uuid, p_delete_event boolean,
    p_restore_status text, p_title text, p_start_datetime timestamptz,
    p_end_datetime timestamptz, p_all_day boolean, p_location text,
    p_description text, p_importance text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_proposal uuid;
BEGIN
    SELECT id INTO v_proposal FROM public.event_change_proposals
    WHERE event_id = p_event_id AND source_id = p_source_id;
    IF v_proposal IS NULL THEN RAISE EXCEPTION 'no proposal for source %', p_source_id; END IF;
    RETURN public.reject_event_change_proposal(p_event_id, p_user_id, v_proposal, NULL,
        p_delete_event, p_restore_status, p_title, p_start_datetime, p_end_datetime,
        p_all_day, p_location, p_description, p_importance, 'user_rejected');
END;
$$;

REVOKE ALL ON FUNCTION public._lock_owned_pending_proposal(uuid, uuid, uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.apply_event_change_proposal(uuid, uuid, uuid, text, text, timestamptz, timestamptz, boolean, text, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.reject_event_change_proposal(uuid, uuid, uuid, text, boolean, text, text, timestamptz, timestamptz, boolean, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.reopen_event_change_proposal(uuid, uuid, uuid, text, text, jsonb, text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.resolve_event_change_proposal(uuid, uuid, uuid, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.apply_event_change_proposal(uuid, uuid, uuid, text, text, timestamptz, timestamptz, boolean, text, text, text, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.reject_event_change_proposal(uuid, uuid, uuid, text, boolean, text, text, timestamptz, timestamptz, boolean, text, text, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.reopen_event_change_proposal(uuid, uuid, uuid, text, text, jsonb, text, boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.resolve_event_change_proposal(uuid, uuid, uuid, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.apply_pending_event_change(uuid, uuid, uuid, text, timestamptz, timestamptz, boolean, text, text, text, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.reject_pending_event_change(uuid, uuid, uuid, boolean, text, text, timestamptz, timestamptz, boolean, text, text, text) TO service_role;

COMMENT ON TABLE public.event_change_proposals IS 'S3 authoritative lifecycle for event update and cancellation review proposals';

ALTER TABLE public.event_repair_audit
    DROP CONSTRAINT IF EXISTS event_repair_audit_action_check;
ALTER TABLE public.event_repair_audit
    ADD CONSTRAINT event_repair_audit_action_check CHECK (action IN (
        'merge_duplicate_group', 'merge_source', 'cancel_event', 'resolve_proposal'
    ));
