-- Integration reauthorization recovery (oauth-reconnect-catch-up.md, section 2)
--
-- Scope note: the spec's own status header says the email half is already
-- delivered by the `integrations_ensure_email_sync_state` trigger (email
-- resumes from durable provider cursors the moment an integration goes
-- active again; no replay/recovery record needed). Only Google Calendar
-- still needs a durable recovery record, because OAuth-blocked events sit
-- parked in `events` and must be explicitly requeued once the user
-- reconnects. `complete_integration_reauthorization` is written generically
-- (any provider can save credentials through it) but only creates a
-- recovery generation for `google_calendar`.

CREATE TABLE public.integration_recoveries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_id uuid NOT NULL REFERENCES public.integrations(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    provider integration_provider NOT NULL,
    reason text NOT NULL CHECK (reason IN ('initial_connection', 'reauthorization')),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'processing', 'waiting', 'completed', 'completed_with_errors',
        'failed', 'superseded'
    )),
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 5,
    next_retry_at timestamptz,
    locked_by text,
    locked_until timestamptz,
    recovery_since timestamptz,
    checkpoint jsonb NOT NULL DEFAULT '{}'::jsonb,
    discovered_count integer NOT NULL DEFAULT 0,
    requeued_count integer NOT NULL DEFAULT 0,
    completed_count integer NOT NULL DEFAULT 0,
    remaining_count integer NOT NULL DEFAULT 0,
    error_code text,
    error_detail text,
    requested_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

-- Defense in depth alongside the natural serialization the credential upsert
-- already gives us (two concurrent callbacks for the same integration both
-- take a row lock on the same `integrations` unique-key row, so the second
-- transaction's supersede-then-insert always runs after the first commits).
CREATE UNIQUE INDEX integration_recoveries_one_active_idx
    ON public.integration_recoveries (integration_id)
    WHERE status IN ('pending', 'processing', 'waiting');

CREATE INDEX integration_recoveries_claim_idx
    ON public.integration_recoveries (requested_at)
    WHERE status = 'pending';

ALTER TABLE public.integration_recoveries ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own integration recoveries"
    ON public.integration_recoveries FOR SELECT TO authenticated
    USING (auth.uid() = user_id);
CREATE POLICY "Service role manages integration recoveries"
    ON public.integration_recoveries FOR ALL TO service_role USING (true) WITH CHECK (true);

COMMENT ON TABLE public.integration_recoveries IS
    'Durable recovery generations created when reauthorization unblocks OAuth-parked work. Never stores credentials.';

-- Tags the specific calendar events a recovery generation requeued, so
-- progress is auditable without storing event contents on the recovery row.
ALTER TABLE public.events
    ADD COLUMN IF NOT EXISTS recovery_id uuid REFERENCES public.integration_recoveries(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS events_recovery_id_idx
    ON public.events (recovery_id) WHERE recovery_id IS NOT NULL;

-- Atomic, service-role-only credential save + recovery scheduling. Both
-- Google and Microsoft OAuth callbacks must call this instead of upserting
-- `integrations` directly, so a reconnect can never save new credentials
-- without also (for Calendar) durably scheduling the recovery of blocked
-- work in the same transaction.
CREATE OR REPLACE FUNCTION public.complete_integration_reauthorization(
    p_user_id uuid,
    p_provider text,
    p_access_token text,
    p_refresh_token text DEFAULT NULL,
    p_token_expiry timestamptz DEFAULT NULL,
    p_scopes text[] DEFAULT '{}',
    p_provider_email text DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_integration_id uuid;
BEGIN
    INSERT INTO public.integrations (
        user_id, provider, status, access_token, refresh_token,
        token_expiry, scopes, provider_email
    ) VALUES (
        p_user_id, p_provider::integration_provider, 'active', p_access_token,
        p_refresh_token, p_token_expiry, COALESCE(p_scopes, '{}'), p_provider_email
    )
    ON CONFLICT (user_id, provider) DO UPDATE SET
        status = 'active',
        access_token = EXCLUDED.access_token,
        -- Google/Microsoft omit the refresh token on a subsequent consent
        -- screen; never overwrite a working one with NULL.
        refresh_token = COALESCE(EXCLUDED.refresh_token, public.integrations.refresh_token),
        token_expiry = EXCLUDED.token_expiry,
        scopes = EXCLUDED.scopes,
        provider_email = COALESCE(EXCLUDED.provider_email, public.integrations.provider_email),
        updated_at = now()
    RETURNING id INTO v_integration_id;

    IF p_provider = 'google_calendar' THEN
        UPDATE public.integration_recoveries
        SET status = 'superseded', updated_at = now()
        WHERE integration_id = v_integration_id
          AND status IN ('pending', 'processing', 'waiting');

        INSERT INTO public.integration_recoveries (
            integration_id, user_id, provider, reason, status
        ) VALUES (
            v_integration_id, p_user_id, p_provider::integration_provider,
            'reauthorization', 'pending'
        );
    END IF;

    RETURN v_integration_id;
END; $$;

CREATE OR REPLACE FUNCTION public.claim_integration_recovery(
    p_worker_id text,
    p_lock_seconds integer DEFAULT 300
) RETURNS SETOF public.integration_recoveries
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_recovery public.integration_recoveries;
BEGIN
    SELECT * INTO v_recovery
    FROM public.integration_recoveries
    WHERE status = 'pending'
      AND attempts < max_attempts
      AND (next_retry_at IS NULL OR next_retry_at <= now())
      AND (locked_until IS NULL OR locked_until < now())
    ORDER BY requested_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF v_recovery.id IS NULL THEN
        RETURN;
    END IF;

    UPDATE public.integration_recoveries SET
        status = 'processing',
        locked_by = p_worker_id,
        locked_until = now() + make_interval(secs => greatest(p_lock_seconds, 1)),
        attempts = attempts + 1,
        started_at = COALESCE(started_at, now()),
        updated_at = now()
    WHERE id = v_recovery.id
    RETURNING * INTO v_recovery;

    RETURN NEXT v_recovery;
END; $$;

CREATE OR REPLACE FUNCTION public.unlock_expired_integration_recoveries()
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_count integer;
BEGIN
    UPDATE public.integration_recoveries
    SET status = 'pending', locked_by = NULL, locked_until = NULL, updated_at = now()
    WHERE status = 'processing' AND locked_until < now();
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END; $$;

REVOKE ALL ON FUNCTION public.complete_integration_reauthorization(uuid, text, text, text, timestamptz, text[], text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.complete_integration_reauthorization(uuid, text, text, text, timestamptz, text[], text) TO service_role;

REVOKE ALL ON FUNCTION public.claim_integration_recovery(text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claim_integration_recovery(text, integer) TO service_role;

REVOKE ALL ON FUNCTION public.unlock_expired_integration_recoveries() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.unlock_expired_integration_recoveries() TO service_role;

COMMENT ON FUNCTION public.complete_integration_reauthorization IS
    'Service-role-only: atomically upserts OAuth credentials and (for google_calendar) supersedes any in-flight recovery generation and schedules a new one';
COMMENT ON FUNCTION public.claim_integration_recovery IS
    'Service-role-only: FOR UPDATE SKIP LOCKED claim of the next pending integration recovery generation';
COMMENT ON FUNCTION public.unlock_expired_integration_recoveries IS
    'Service-role-only: returns crashed-worker recovery claims to pending';
