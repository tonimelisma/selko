-- Durable polling-only email ingestion v2.
-- Provider cursors remain on integrations/email_folders. These tables are the
-- recovery boundary around those cursors: provider identity discovery is
-- committed before body, attachment, or LLM work is attempted.

CREATE TABLE public.email_sync_state (
    integration_id uuid PRIMARY KEY REFERENCES public.integrations(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    provider text NOT NULL CHECK (provider IN ('gmail', 'outlook')),
    initial_watermark_at timestamptz NOT NULL,
    next_poll_at timestamptz NOT NULL DEFAULT now(),
    lease_owner text,
    lease_expires_at timestamptz,
    last_started_at timestamptz,
    last_discovery_at timestamptz,
    last_success_at timestamptz,
    last_reconciled_at timestamptz,
    consecutive_failures integer NOT NULL DEFAULT 0,
    last_error_code text,
    last_error_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX email_sync_state_due_idx
    ON public.email_sync_state (next_poll_at, last_success_at NULLS FIRST);

CREATE TABLE public.email_sync_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_id uuid NOT NULL REFERENCES public.integrations(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    provider text NOT NULL CHECK (provider IN ('gmail', 'outlook')),
    run_kind text NOT NULL CHECK (run_kind IN (
        'initial', 'incremental', 'daily_reconcile', 'weekly_reconcile', 'manual_repair'
    )),
    status text NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'abandoned')),
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    folders_attempted integer NOT NULL DEFAULT 0,
    folders_completed integer NOT NULL DEFAULT 0,
    provider_ids_seen integer NOT NULL DEFAULT 0,
    ingestion_items_inserted integer NOT NULL DEFAULT 0,
    ingestion_items_existing integer NOT NULL DEFAULT 0,
    error_code text,
    error_detail text
);

CREATE INDEX email_sync_runs_integration_started_idx
    ON public.email_sync_runs (integration_id, started_at DESC);

CREATE TABLE public.email_ingestion_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_id uuid NOT NULL REFERENCES public.integrations(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    provider text NOT NULL CHECK (provider IN ('gmail', 'outlook')),
    provider_message_id text NOT NULL,
    provider_folder_ids text[] NOT NULL DEFAULT '{}',
    change_kind text NOT NULL DEFAULT 'upsert'
        CHECK (change_kind IN ('upsert', 'membership_change', 'removed')),
    first_discovered_at timestamptz NOT NULL DEFAULT now(),
    last_discovered_at timestamptz NOT NULL DEFAULT now(),
    acquisition_status text NOT NULL DEFAULT 'pending'
        CHECK (acquisition_status IN ('pending', 'processing', 'completed', 'retry', 'dead_letter', 'removed')),
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 8,
    next_retry_at timestamptz,
    lease_owner text,
    lease_expires_at timestamptz,
    last_error_code text,
    last_error_at timestamptz,
    email_id uuid REFERENCES public.emails(id) ON DELETE SET NULL,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (integration_id, provider_message_id)
);

CREATE INDEX email_ingestion_items_claim_idx
    ON public.email_ingestion_items (acquisition_status, next_retry_at, created_at)
    WHERE acquisition_status IN ('pending', 'retry', 'processing');

CREATE TABLE public.operational_incidents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_key text NOT NULL UNIQUE,
    integration_id uuid REFERENCES public.integrations(id) ON DELETE CASCADE,
    user_id uuid REFERENCES public.users(id) ON DELETE CASCADE,
    incident_type text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('warning', 'critical')),
    status text NOT NULL CHECK (status IN ('open', 'resolved')),
    safe_summary text NOT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    opened_notification_sent_at timestamptz,
    resolved_notification_sent_at timestamptz
);

CREATE TABLE public.graph_api_failures (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    environment text NOT NULL,
    integration_id uuid REFERENCES public.integrations(id) ON DELETE CASCADE,
    graph_surface text NOT NULL CHECK (graph_surface IN ('outlook_mail', 'onedrive')),
    operation text NOT NULL,
    http_method text NOT NULL,
    safe_url_template text NOT NULL,
    http_status integer,
    graph_error_code text,
    request_id text,
    client_request_id text,
    retry_after_seconds integer,
    failure_class text NOT NULL,
    response_summary text,
    run_id uuid REFERENCES public.email_sync_runs(id) ON DELETE SET NULL,
    attempt integer NOT NULL DEFAULT 1,
    will_retry boolean NOT NULL DEFAULT false,
    resolved_at timestamptz
);

CREATE INDEX graph_api_failures_surface_time_idx
    ON public.graph_api_failures (graph_surface, occurred_at DESC);
CREATE INDEX graph_api_failures_class_time_idx
    ON public.graph_api_failures (failure_class, occurred_at DESC);
CREATE INDEX graph_api_failures_unresolved_idx
    ON public.graph_api_failures (occurred_at DESC) WHERE resolved_at IS NULL;

ALTER TABLE public.attachments
    ADD COLUMN IF NOT EXISTS ingestion_status text NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS max_attempts integer NOT NULL DEFAULT 8,
    ADD COLUMN IF NOT EXISTS next_retry_at timestamptz,
    ADD COLUMN IF NOT EXISTS locked_by text,
    ADD COLUMN IF NOT EXISTS locked_until timestamptz,
    ADD COLUMN IF NOT EXISTS ingestion_error_code text;

ALTER TABLE public.attachments
    DROP CONSTRAINT IF EXISTS attachments_ingestion_status_check;
ALTER TABLE public.attachments
    ADD CONSTRAINT attachments_ingestion_status_check
    CHECK (ingestion_status IN ('pending', 'processing', 'stored', 'unsupported', 'retry', 'dead_letter'));

UPDATE public.attachments
SET ingestion_status = 'stored'
WHERE storage_path IS NOT NULL AND ingestion_status = 'pending';

-- This is intentionally non-destructive. Existing duplicate rows must be
-- resolved by an explicit, reviewed data repair before applying the constraint.
CREATE UNIQUE INDEX IF NOT EXISTS attachments_email_provider_attachment_idx
    ON public.attachments (email_id, provider_attachment_id)
    WHERE provider_attachment_id IS NOT NULL AND provider_attachment_id <> '';
CREATE INDEX IF NOT EXISTS attachments_claim_idx
    ON public.attachments (ingestion_status, next_retry_at, created_at)
    WHERE ingestion_status IN ('pending', 'retry', 'processing');

ALTER TABLE public.email_sync_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.email_sync_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.email_ingestion_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.operational_incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.graph_api_failures ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own email sync health"
    ON public.email_sync_state FOR SELECT TO authenticated
    USING (auth.uid() = user_id);
CREATE POLICY "Service role manages email sync state"
    ON public.email_sync_state FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Service role manages email sync runs"
    ON public.email_sync_runs FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Service role manages ingestion items"
    ON public.email_ingestion_items FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Service role manages operational incidents"
    ON public.operational_incidents FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Service role manages Graph failures"
    ON public.graph_api_failures FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE OR REPLACE VIEW public.email_sync_health
WITH (security_invoker = true) AS
SELECT s.integration_id, s.user_id, s.provider, s.initial_watermark_at,
       s.next_poll_at, s.last_started_at, s.last_discovery_at,
       s.last_success_at, s.last_reconciled_at, s.consecutive_failures,
       s.last_error_code, s.last_error_at, i.provider_email,
       i.status AS integration_status
FROM public.email_sync_state s
JOIN public.integrations i ON i.id = s.integration_id;
GRANT SELECT ON public.email_sync_health TO authenticated;

-- Supabase does not grant Data API privileges on new public tables by default.
-- RLS above is the row-level authorization layer; these grants only make the
-- operations those policies already allow reachable through PostgREST. Without
-- them the worker's service-role reads and writes fail with "permission
-- denied", and the security_invoker health view returns nothing.
REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE
    public.email_sync_state,
    public.email_sync_runs,
    public.email_ingestion_items,
    public.operational_incidents,
    public.graph_api_failures
FROM anon, authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    public.email_sync_state,
    public.email_sync_runs,
    public.email_ingestion_items,
    public.operational_incidents,
    public.graph_api_failures
TO service_role;

-- Users may read only their own polling health; operational state and
-- service-only error details stay unreadable to them.
GRANT SELECT ON TABLE public.email_sync_state TO authenticated;

CREATE OR REPLACE FUNCTION public.claim_due_email_sync(p_worker_id text, p_lease_seconds integer)
RETURNS TABLE (integration_id uuid, user_id uuid, provider text, run_id uuid,
               run_kind text, lease_expires_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_state public.email_sync_state; v_run_id uuid; v_kind text;
BEGIN
    SELECT s.* INTO v_state FROM public.email_sync_state s
    JOIN public.integrations i ON i.id = s.integration_id
    WHERE i.status = 'active' AND s.next_poll_at <= now()
      AND (s.lease_expires_at IS NULL OR s.lease_expires_at <= now())
    ORDER BY s.next_poll_at, s.last_success_at NULLS FIRST
    LIMIT 1 FOR UPDATE OF s SKIP LOCKED;
    IF v_state.integration_id IS NULL THEN RETURN; END IF;
    v_kind := CASE WHEN v_state.last_success_at IS NULL THEN 'initial' ELSE 'incremental' END;
    INSERT INTO public.email_sync_runs (integration_id, user_id, provider, run_kind, status)
    VALUES (v_state.integration_id, v_state.user_id, v_state.provider, v_kind, 'running')
    RETURNING id INTO v_run_id;
    UPDATE public.email_sync_state SET lease_owner = p_worker_id,
        lease_expires_at = now() + make_interval(secs => greatest(p_lease_seconds, 1)),
        last_started_at = now(), updated_at = now()
    WHERE email_sync_state.integration_id = v_state.integration_id;
    RETURN QUERY SELECT v_state.integration_id, v_state.user_id, v_state.provider,
        v_run_id, v_kind, now() + make_interval(secs => greatest(p_lease_seconds, 1));
END; $$;

CREATE OR REPLACE FUNCTION public.claim_due_email_reconciliation(p_worker_id text, p_lease_seconds integer)
RETURNS TABLE (integration_id uuid, user_id uuid, provider text, run_id uuid,
               run_kind text, lease_expires_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_state public.email_sync_state; v_run_id uuid; v_kind text;
BEGIN
    SELECT s.* INTO v_state FROM public.email_sync_state s
    JOIN public.integrations i ON i.id = s.integration_id
    WHERE i.status = 'active'
      AND (s.lease_expires_at IS NULL OR s.lease_expires_at <= now())
      AND (s.last_reconciled_at IS NULL OR s.last_reconciled_at <= now() - interval '1 day')
      AND s.next_poll_at > now()
    ORDER BY s.last_reconciled_at NULLS FIRST, s.next_poll_at
    LIMIT 1 FOR UPDATE OF s SKIP LOCKED;
    IF v_state.integration_id IS NULL THEN RETURN; END IF;
    v_kind := CASE WHEN v_state.last_reconciled_at IS NOT NULL
                        AND v_state.last_reconciled_at <= now() - interval '7 days'
                   THEN 'weekly_reconcile' ELSE 'daily_reconcile' END;
    INSERT INTO public.email_sync_runs (integration_id, user_id, provider, run_kind, status)
    VALUES (v_state.integration_id, v_state.user_id, v_state.provider, v_kind, 'running')
    RETURNING id INTO v_run_id;
    UPDATE public.email_sync_state SET lease_owner = p_worker_id,
        lease_expires_at = now() + make_interval(secs => greatest(p_lease_seconds, 1)),
        last_started_at = now(), updated_at = now()
    WHERE email_sync_state.integration_id = v_state.integration_id;
    RETURN QUERY SELECT v_state.integration_id, v_state.user_id, v_state.provider,
        v_run_id, v_kind, now() + make_interval(secs => greatest(p_lease_seconds, 1));
END; $$;

CREATE OR REPLACE FUNCTION public.heartbeat_email_sync(p_integration_id uuid, p_worker_id text, p_lease_seconds integer)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    UPDATE public.email_sync_state SET lease_expires_at = now() + make_interval(secs => greatest(p_lease_seconds, 1)), updated_at = now()
    WHERE integration_id = p_integration_id AND lease_owner = p_worker_id AND lease_expires_at > now();
    RETURN FOUND;
END; $$;

CREATE OR REPLACE FUNCTION public.complete_email_sync(
    p_integration_id uuid, p_run_id uuid, p_worker_id text,
    p_poll_interval_seconds integer DEFAULT 300, p_reconciled boolean DEFAULT false)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.email_sync_state WHERE integration_id = p_integration_id
                   AND lease_owner = p_worker_id AND lease_expires_at > now()) THEN RETURN false; END IF;
    UPDATE public.email_sync_runs SET status = 'completed', completed_at = now()
    WHERE id = p_run_id AND integration_id = p_integration_id AND status = 'running';
    UPDATE public.email_sync_state SET lease_owner = NULL, lease_expires_at = NULL,
        last_discovery_at = now(), last_success_at = now(),
        last_reconciled_at = CASE WHEN p_reconciled THEN now() ELSE last_reconciled_at END,
        consecutive_failures = 0, last_error_code = NULL, last_error_at = NULL,
        next_poll_at = now() + make_interval(secs => greatest(p_poll_interval_seconds, 1)), updated_at = now()
    WHERE integration_id = p_integration_id AND lease_owner = p_worker_id;
    RETURN true;
END; $$;

CREATE OR REPLACE FUNCTION public.fail_email_sync(
    p_integration_id uuid, p_run_id uuid, p_worker_id text, p_error_code text,
    p_error_detail text DEFAULT NULL, p_retry_base_seconds integer DEFAULT 60,
    p_retry_max_seconds integer DEFAULT 1800, p_auth_failure boolean DEFAULT false)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_failures integer; v_delay integer;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.email_sync_state WHERE integration_id = p_integration_id AND lease_owner = p_worker_id) THEN RETURN false; END IF;
    SELECT consecutive_failures + 1 INTO v_failures FROM public.email_sync_state WHERE integration_id = p_integration_id FOR UPDATE;
    v_delay := LEAST(p_retry_max_seconds, GREATEST(p_retry_base_seconds, 1) * power(2, LEAST(v_failures - 1, 5))::integer);
    UPDATE public.email_sync_runs SET status = 'failed', completed_at = now(), error_code = left(p_error_code, 100), error_detail = left(p_error_detail, 500)
    WHERE id = p_run_id AND integration_id = p_integration_id AND status = 'running';
    UPDATE public.email_sync_state SET lease_owner = NULL, lease_expires_at = NULL, consecutive_failures = v_failures,
        last_error_code = left(p_error_code, 100), last_error_at = now(), next_poll_at = now() + make_interval(secs => v_delay), updated_at = now()
    WHERE integration_id = p_integration_id;
    IF p_auth_failure THEN UPDATE public.integrations SET status = 'expired', updated_at = now() WHERE id = p_integration_id; END IF;
    RETURN true;
END; $$;

CREATE OR REPLACE FUNCTION public.upsert_discovered_email_items(
    p_integration_id uuid, p_run_id uuid, p_items jsonb,
    p_cursor text DEFAULT NULL, p_folder_id uuid DEFAULT NULL)
RETURNS TABLE (inserted_count integer, existing_count integer, provider_ids_seen integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_user_id uuid; v_provider text; v_seen integer := 0; v_existing integer := 0;
BEGIN
    SELECT user_id, provider INTO v_user_id, v_provider FROM public.email_sync_state WHERE integration_id = p_integration_id;
    IF v_user_id IS NULL THEN RAISE EXCEPTION 'Unknown email integration'; END IF;
    SELECT count(*) INTO v_seen FROM jsonb_array_elements(COALESCE(p_items, '[]'::jsonb));
    SELECT count(*) INTO v_existing FROM public.email_ingestion_items i
    WHERE i.integration_id = p_integration_id AND i.provider_message_id IN
        (SELECT value->>'provider_message_id' FROM jsonb_array_elements(COALESCE(p_items, '[]'::jsonb)));
    INSERT INTO public.email_ingestion_items (integration_id, user_id, provider, provider_message_id, provider_folder_ids, change_kind)
    SELECT p_integration_id, v_user_id, v_provider, item->>'provider_message_id',
        ARRAY(SELECT jsonb_array_elements_text(COALESCE(item->'provider_folder_ids', '[]'::jsonb))),
        COALESCE(item->>'change_kind', 'upsert')
    FROM jsonb_array_elements(COALESCE(p_items, '[]'::jsonb)) item
    WHERE NULLIF(item->>'provider_message_id', '') IS NOT NULL
    ON CONFLICT (integration_id, provider_message_id) DO UPDATE SET
        provider_folder_ids = ARRAY(SELECT DISTINCT value FROM unnest(public.email_ingestion_items.provider_folder_ids || EXCLUDED.provider_folder_ids) value),
        change_kind = CASE WHEN public.email_ingestion_items.acquisition_status = 'completed' THEN public.email_ingestion_items.change_kind ELSE EXCLUDED.change_kind END,
        last_discovered_at = now(),
        acquisition_status = CASE WHEN public.email_ingestion_items.acquisition_status IN ('retry', 'pending') THEN 'pending' ELSE public.email_ingestion_items.acquisition_status END,
        updated_at = now();
    -- The RETURNS TABLE column provider_ids_seen shadows the run column of the
    -- same name, so every read side of this UPDATE must be table-qualified.
    UPDATE public.email_sync_runs r SET provider_ids_seen = r.provider_ids_seen + v_seen,
        ingestion_items_inserted = r.ingestion_items_inserted + greatest(v_seen - v_existing, 0),
        ingestion_items_existing = r.ingestion_items_existing + least(v_seen, v_existing)
    WHERE r.id = p_run_id AND r.status = 'running';
    IF p_folder_id IS NULL AND p_cursor IS NOT NULL THEN
        UPDATE public.integrations SET sync_cursor = p_cursor, last_sync_at = now(), updated_at = now() WHERE id = p_integration_id;
    ELSIF p_folder_id IS NOT NULL AND p_cursor IS NOT NULL THEN
        UPDATE public.email_folders SET sync_cursor = p_cursor, updated_at = now() WHERE id = p_folder_id AND integration_id = p_integration_id;
    END IF;
    RETURN QUERY SELECT greatest(v_seen - v_existing, 0), least(v_seen, v_existing), v_seen;
END; $$;

CREATE OR REPLACE FUNCTION public.claim_email_ingestion_item(p_worker_id text, p_lease_seconds integer DEFAULT 900)
RETURNS SETOF public.email_ingestion_items LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_item public.email_ingestion_items;
BEGIN
    SELECT i.* INTO v_item FROM public.email_ingestion_items i
    WHERE i.acquisition_status IN ('pending', 'retry', 'processing') AND i.attempts < i.max_attempts
      AND (i.next_retry_at IS NULL OR i.next_retry_at <= now()) AND (i.lease_expires_at IS NULL OR i.lease_expires_at <= now())
    ORDER BY i.created_at FOR UPDATE SKIP LOCKED LIMIT 1;
    IF v_item.id IS NULL THEN RETURN; END IF;
    UPDATE public.email_ingestion_items SET acquisition_status = 'processing', attempts = attempts + 1,
        lease_owner = p_worker_id, lease_expires_at = now() + make_interval(secs => greatest(p_lease_seconds, 1)), updated_at = now()
    WHERE id = v_item.id RETURNING * INTO v_item;
    RETURN NEXT v_item;
END; $$;

CREATE OR REPLACE FUNCTION public.complete_email_ingestion_item(p_item_id uuid, p_worker_id text, p_email_id uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    UPDATE public.email_ingestion_items SET acquisition_status = 'completed', email_id = p_email_id, completed_at = now(),
        lease_owner = NULL, lease_expires_at = NULL, last_error_code = NULL, updated_at = now()
    WHERE id = p_item_id AND acquisition_status = 'processing' AND lease_owner = p_worker_id;
    RETURN FOUND;
END; $$;

CREATE OR REPLACE FUNCTION public.fail_email_ingestion_item(
    p_item_id uuid, p_worker_id text, p_error_code text, p_retry_base_seconds integer DEFAULT 60,
    p_retry_max_seconds integer DEFAULT 1800, p_terminal boolean DEFAULT false)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_attempts integer; v_max integer; v_retry boolean; v_delay integer;
BEGIN
    SELECT attempts, max_attempts INTO v_attempts, v_max FROM public.email_ingestion_items WHERE id = p_item_id AND lease_owner = p_worker_id FOR UPDATE;
    IF v_attempts IS NULL THEN RETURN false; END IF;
    v_retry := NOT p_terminal AND v_attempts < v_max;
    v_delay := LEAST(p_retry_max_seconds, GREATEST(p_retry_base_seconds, 1) * power(2, LEAST(v_attempts - 1, 5))::integer);
    UPDATE public.email_ingestion_items SET acquisition_status = CASE WHEN v_retry THEN 'retry' ELSE 'dead_letter' END,
        next_retry_at = CASE WHEN v_retry THEN now() + make_interval(secs => v_delay) ELSE NULL END,
        last_error_code = left(p_error_code, 100), last_error_at = now(), lease_owner = NULL, lease_expires_at = NULL, updated_at = now()
    WHERE id = p_item_id AND lease_owner = p_worker_id;
    RETURN FOUND;
END; $$;

CREATE OR REPLACE FUNCTION public.claim_email_attachment(p_worker_id text, p_lease_seconds integer DEFAULT 900)
RETURNS SETOF public.attachments LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_attachment public.attachments;
BEGIN
    SELECT a.* INTO v_attachment FROM public.attachments a
    WHERE a.ingestion_status IN ('pending', 'retry', 'processing') AND a.attempts < a.max_attempts
      AND (a.next_retry_at IS NULL OR a.next_retry_at <= now()) AND (a.locked_until IS NULL OR a.locked_until <= now())
    ORDER BY a.created_at FOR UPDATE SKIP LOCKED LIMIT 1;
    IF v_attachment.id IS NULL THEN RETURN; END IF;
    UPDATE public.attachments SET ingestion_status = 'processing', attempts = attempts + 1,
        locked_by = p_worker_id, locked_until = now() + make_interval(secs => greatest(p_lease_seconds, 1))
    WHERE id = v_attachment.id RETURNING * INTO v_attachment;
    RETURN NEXT v_attachment;
END; $$;

CREATE OR REPLACE FUNCTION public.finish_email_attachment(p_attachment_id uuid, p_worker_id text, p_status text, p_error_code text DEFAULT NULL)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF p_status NOT IN ('stored', 'unsupported', 'retry', 'dead_letter') THEN RAISE EXCEPTION 'Invalid attachment terminal state'; END IF;
    UPDATE public.attachments SET ingestion_status = p_status, ingestion_error_code = left(p_error_code, 100),
        locked_by = NULL, locked_until = NULL, next_retry_at = NULL WHERE id = p_attachment_id AND locked_by = p_worker_id;
    RETURN FOUND;
END; $$;

REVOKE ALL ON FUNCTION public.claim_due_email_sync(text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_due_email_reconciliation(text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.heartbeat_email_sync(uuid, text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.complete_email_sync(uuid, uuid, text, integer, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.fail_email_sync(uuid, uuid, text, text, text, integer, integer, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.upsert_discovered_email_items(uuid, uuid, jsonb, text, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_email_ingestion_item(text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.complete_email_ingestion_item(uuid, text, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.fail_email_ingestion_item(uuid, text, text, integer, integer, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_email_attachment(text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.finish_email_attachment(uuid, text, text, text) FROM PUBLIC;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO service_role;

-- Idempotent migration/backfill. It creates durable state for existing active
-- email integrations and does not requeue already processed email rows.
INSERT INTO public.email_sync_state (integration_id, user_id, provider, initial_watermark_at)
SELECT i.id, i.user_id, i.provider::text,
       GREATEST(COALESCE((SELECT min(e.date_sent) FROM public.emails e
                          WHERE e.integration_id = i.id AND e.email_provider = i.provider::text), now() - interval '14 days'),
                now() - interval '14 days')
FROM public.integrations i
WHERE i.provider::text IN ('gmail', 'outlook') AND i.status = 'active'
ON CONFLICT (integration_id) DO NOTHING;

INSERT INTO public.email_ingestion_items (integration_id, user_id, provider, provider_message_id,
                                          provider_folder_ids, acquisition_status, email_id, completed_at)
SELECT e.integration_id, e.user_id, e.email_provider, e.provider_message_id,
       COALESCE(e.provider_folder_ids, '{}'), 'completed', e.id, now()
FROM public.emails e
WHERE e.integration_id IS NOT NULL AND e.email_provider IN ('gmail', 'outlook')
ON CONFLICT (integration_id, provider_message_id) DO UPDATE SET
    email_id = COALESCE(public.email_ingestion_items.email_id, EXCLUDED.email_id),
    acquisition_status = CASE WHEN public.email_ingestion_items.acquisition_status = 'completed' THEN 'completed' ELSE public.email_ingestion_items.acquisition_status END,
    provider_folder_ids = ARRAY(SELECT DISTINCT value FROM unnest(public.email_ingestion_items.provider_folder_ids || EXCLUDED.provider_folder_ids) value),
    updated_at = now();

COMMENT ON TABLE public.email_sync_state IS 'Durable per-integration polling lease and health state';
COMMENT ON TABLE public.email_sync_runs IS 'Append-only audit of provider discovery and reconciliation runs';
COMMENT ON TABLE public.email_ingestion_items IS 'Durable provider identity boundary before message acquisition';
COMMENT ON TABLE public.operational_incidents IS 'Deduplicated safe operational notifications';
COMMENT ON TABLE public.graph_api_failures IS 'Redacted Microsoft Graph failure ledger';

-- Existing downstream email processing must wait for independent attachment
-- work. Unsupported and dead-lettered files are terminal and do not block the
-- body from reaching the LLM.
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
        UPDATE public.emails SET processing_status = 'processing', locked_by = p_worker_id,
            locked_until = now() + make_interval(secs => greatest(p_lock_duration_seconds, 1)),
            attempts = attempts + 1 WHERE id = v_email.id RETURNING * INTO v_email;
        RETURN NEXT v_email;
    END IF;
END; $$;
