-- S1: durable email work and truthful health.
--
-- Two independent state machines get fenced RPCs and an enforced invariant:
--
--   1. emails.processing_status — LLM extraction work. A `pending` row must
--      be genuinely claimable (attempts left, no owner, no unexpired lock).
--      claim_unprocessed_email now opportunistically reclaims one expired
--      `processing` lease per call before claiming a fresh pending row, so a
--      crashed worker's row recovers on the next claim, not on a restart.
--   2. email_sync_state / email_sync_runs — provider discovery leases. Every
--      claim is now generation-fenced end to end (claim -> heartbeat ->
--      complete/fail), and at most one `running` run may exist per
--      integration; the previous running run is marked `abandoned` before a
--      new generation is issued.
--
-- health_work_state() replaces health_dead_letter_counts()/health_poll_slo()
-- with one counted RPC whose ready/processing/stale/unclaimable predicates
-- are pinned in test_schema_contract.py and must match the claim RPC exactly.

-- ---------------------------------------------------------------------------
-- 1. Repair historical rows before the new invariant can be enforced.
-- ---------------------------------------------------------------------------

-- A `pending` row that cannot actually be claimed (exhausted attempts, or an
-- inconsistent lock) is repaired to a terminal `failed` row rather than
-- replayed here. This mirrors the production repair already performed by
-- hand; the migration makes the same result reproducible everywhere else.
UPDATE public.emails
SET processing_status = 'failed',
    dead_letter_reason = CASE
        WHEN attempts >= max_attempts THEN 'legacy_attempts_exhausted'
        ELSE 'legacy_inconsistent_lock'
    END,
    dead_letter_at = now(),
    locked_by = NULL,
    locked_until = NULL
WHERE processing_status = 'pending'
  AND (attempts >= max_attempts OR locked_by IS NOT NULL OR locked_until IS NOT NULL);

ALTER TABLE public.emails DROP CONSTRAINT IF EXISTS emails_pending_is_claimable_check;
ALTER TABLE public.emails ADD CONSTRAINT emails_pending_is_claimable_check
    CHECK (
        processing_status <> 'pending'
        OR (attempts < max_attempts AND locked_by IS NULL AND locked_until IS NULL)
    );

-- The startup sweeper predates the invariant above: it flipped any expired
-- `processing` row straight back to `pending` regardless of attempts, which
-- would violate the new CHECK for a row that is both expired and exhausted.
-- Route it through the same retry-or-terminal decision as the claim RPC's
-- reclaim phase.
CREATE OR REPLACE FUNCTION public.unlock_expired_email_locks()
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    v_count integer;
BEGIN
    UPDATE public.emails
    SET processing_status = 'pending',
        processing_error = NULL,
        locked_by = NULL,
        locked_until = NULL
    WHERE processing_status = 'processing'
      AND locked_until < now()
      AND attempts < max_attempts;
    GET DIAGNOSTICS v_count = ROW_COUNT;

    UPDATE public.emails
    SET processing_status = 'failed',
        dead_letter_reason = 'lease_expired_at_limit',
        dead_letter_at = now(),
        locked_by = NULL,
        locked_until = NULL
    WHERE processing_status = 'processing'
      AND locked_until < now()
      AND attempts >= max_attempts;

    RETURN v_count;
END;
$$;

COMMENT ON FUNCTION public.unlock_expired_email_locks()
    IS 'Startup recovery: retries expired leases with attempts remaining, terminates exhausted ones (CHECK-safe)';

-- ---------------------------------------------------------------------------
-- 2. Fenced email processing RPCs.
-- ---------------------------------------------------------------------------

-- Single source of truth for "is this pending email actually claimable" —
-- claim_unprocessed_email's SELECT and health_work_state's ready_emails count
-- both call this instead of keeping two copies of the predicate that could
-- silently drift apart (the exact failure mode this migration exists to
-- close: a row reported healthy that the claim RPC will never pick up).
CREATE OR REPLACE FUNCTION public._email_is_claimable(e public.emails) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT e.processing_status = 'pending'
       AND e.attempts < e.max_attempts
       AND (e.locked_until IS NULL OR e.locked_until < now())
       AND (e.next_retry_at IS NULL OR e.next_retry_at <= now())
       AND NOT EXISTS (
           SELECT 1 FROM public.attachments a
           WHERE a.email_id = e.id
             AND a.ingestion_status IN ('pending', 'processing', 'retry')
       )
$$;

-- Claim now does two things per call: opportunistically reclaim one expired
-- `processing` lease (retry if attempts remain, otherwise fail it at the
-- limit), then claim the oldest eligible pending row via the shared
-- claimability predicate above.
CREATE OR REPLACE FUNCTION public.claim_unprocessed_email(
    p_worker_id text,
    p_lock_duration_seconds integer DEFAULT 300
) RETURNS SETOF public.emails
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_stale public.emails;
    v_email public.emails;
BEGIN
    SELECT e.* INTO v_stale
    FROM public.emails e
    WHERE e.processing_status = 'processing'
      AND e.locked_until IS NOT NULL
      AND e.locked_until < now()
    ORDER BY e.locked_until ASC
    LIMIT 1 FOR UPDATE SKIP LOCKED;

    IF v_stale.id IS NOT NULL THEN
        IF v_stale.attempts < v_stale.max_attempts THEN
            UPDATE public.emails
            SET processing_status = 'pending',
                processing_error = NULL,
                locked_by = NULL,
                locked_until = NULL
            WHERE id = v_stale.id;
        ELSE
            UPDATE public.emails
            SET processing_status = 'failed',
                dead_letter_reason = 'lease_expired_at_limit',
                dead_letter_at = now(),
                locked_by = NULL,
                locked_until = NULL
            WHERE id = v_stale.id;
        END IF;
    END IF;

    SELECT e.* INTO v_email
    FROM public.emails e
    WHERE public._email_is_claimable(e)
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
    IS 'Atomically reclaim one expired processing lease, then claim next pending email; increments its lease generation';

-- Fenced failure transition: only the current (locked_by, lock_generation)
-- owner may retry-or-terminate the row it holds. A stale worker's call is a
-- no-op that reports fenced=true so the caller never overwrites a
-- replacement worker's claim.
--
-- p_error_detail is accepted for parity with fail_email_sync's signature but
-- intentionally not persisted: emails has one processing_error column (no
-- separate detail column like email_sync_runs.error_detail), and the pinned
-- integration test asserts processing_error equals the code exactly.
CREATE OR REPLACE FUNCTION public.fail_email_processing(
    p_email_id uuid,
    p_worker_id text,
    p_generation bigint,
    p_error_code text,
    p_error_detail text,
    p_retry_base_seconds integer,
    p_retry_max_seconds integer
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_email public.emails;
    v_delay integer;
    v_next_retry_at timestamptz;
BEGIN
    SELECT * INTO v_email FROM public.emails WHERE id = p_email_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'email % not found', p_email_id;
    END IF;

    IF v_email.locked_by IS DISTINCT FROM p_worker_id
       OR v_email.lock_generation IS DISTINCT FROM p_generation THEN
        RETURN jsonb_build_object('fenced', true, 'status', v_email.processing_status);
    END IF;

    IF v_email.attempts < v_email.max_attempts THEN
        v_delay := LEAST(
            greatest(p_retry_max_seconds, 1),
            greatest(p_retry_base_seconds, 1) * power(2, LEAST(greatest(v_email.attempts - 1, 0), 5))::integer
        );
        v_next_retry_at := now() + make_interval(secs => v_delay);
        UPDATE public.emails
        SET processing_status = 'pending',
            processing_error = left(p_error_code, 100),
            locked_by = NULL,
            locked_until = NULL,
            next_retry_at = v_next_retry_at
        WHERE id = p_email_id;
        RETURN jsonb_build_object(
            'fenced', false, 'status', 'pending',
            'attempts', v_email.attempts, 'next_retry_at', v_next_retry_at
        );
    ELSE
        UPDATE public.emails
        SET processing_status = 'failed',
            processing_error = left(p_error_code, 100),
            dead_letter_reason = left(p_error_code, 100),
            dead_letter_at = now(),
            locked_by = NULL,
            locked_until = NULL
        WHERE id = p_email_id;
        RETURN jsonb_build_object('fenced', false, 'status', 'failed', 'attempts', v_email.attempts);
    END IF;
END; $$;

REVOKE ALL ON FUNCTION public.fail_email_processing(uuid, text, bigint, text, text, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.fail_email_processing(uuid, text, bigint, text, text, integer, integer) TO service_role;
COMMENT ON FUNCTION public.fail_email_processing(uuid, text, bigint, text, text, integer, integer)
    IS 'Fenced retry-or-terminate transition; a stale (worker,generation) is a no-op';

-- reprocess_email may reset any row without a live processing lease
-- (terminal or a legacy pending/exhausted row), and now explicitly refuses —
-- rather than silently ignoring — a row with a live lease.
CREATE OR REPLACE FUNCTION public.reprocess_email(
    p_user_id uuid,
    p_email_id uuid
) RETURNS SETOF public.emails
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_email public.emails;
BEGIN
    IF auth.uid() IS DISTINCT FROM p_user_id AND auth.role() <> 'service_role' THEN
        RAISE EXCEPTION 'Cannot reprocess another user''s email';
    END IF;

    SELECT * INTO v_email FROM public.emails
    WHERE id = p_email_id AND user_id = p_user_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    IF v_email.processing_status = 'processing'
       AND v_email.locked_until IS NOT NULL
       AND v_email.locked_until > now() THEN
        RAISE EXCEPTION 'email_actively_leased';
    END IF;

    RETURN QUERY
    UPDATE public.emails
    SET processing_status = 'pending',
        processing_error = NULL,
        processing_outcome = NULL,
        processing_explanation = NULL,
        processing_result = NULL,
        processed_at = NULL,
        locked_by = NULL,
        locked_until = NULL,
        next_retry_at = NULL,
        dead_letter_reason = NULL,
        dead_letter_at = NULL,
        attempts = 0,
        lock_generation = lock_generation + 1
    WHERE id = p_email_id
    RETURNING public.emails.*;
END;
$$;

GRANT EXECUTE ON FUNCTION public.reprocess_email(uuid, uuid) TO authenticated, service_role;
COMMENT ON FUNCTION public.reprocess_email(uuid, uuid)
    IS 'Resets any row without a live processing lease back to pending; raises email_actively_leased otherwise';

-- ---------------------------------------------------------------------------
-- 3. Generation-fence provider discovery runs.
-- ---------------------------------------------------------------------------

ALTER TABLE public.email_sync_state
    ADD COLUMN IF NOT EXISTS lease_generation bigint NOT NULL DEFAULT 0;
ALTER TABLE public.email_sync_runs
    ADD COLUMN IF NOT EXISTS lease_generation bigint NOT NULL DEFAULT 0;

-- Before the partial unique index below, collapse any pre-existing duplicate
-- `running` rows per integration (there should be at most a handful, from
-- crashes that predate this migration): keep the most recently started one
-- running, mark the rest abandoned.
UPDATE public.email_sync_runs r
SET status = 'abandoned', completed_at = now()
WHERE r.status = 'running'
  AND r.id <> (
      SELECT r2.id FROM public.email_sync_runs r2
      WHERE r2.integration_id = r.integration_id AND r2.status = 'running'
      ORDER BY r2.started_at DESC, r2.id DESC
      LIMIT 1
  );

CREATE UNIQUE INDEX IF NOT EXISTS email_sync_runs_one_running_per_integration
    ON public.email_sync_runs(integration_id)
    WHERE status = 'running';

DROP FUNCTION IF EXISTS public.claim_due_email_sync(text, integer);
CREATE FUNCTION public.claim_due_email_sync(p_worker_id text, p_lease_seconds integer)
RETURNS TABLE (integration_id uuid, user_id uuid, provider text, run_id uuid,
               run_kind text, lease_generation bigint, lease_expires_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_state public.email_sync_state; v_run_id uuid; v_kind text; v_generation bigint;
BEGIN
    SELECT s.* INTO v_state FROM public.email_sync_state s
    JOIN public.integrations i ON i.id = s.integration_id
    WHERE i.status = 'active' AND s.next_poll_at <= now()
      AND (s.lease_expires_at IS NULL OR s.lease_expires_at <= now())
    ORDER BY s.next_poll_at, s.last_success_at NULLS FIRST
    LIMIT 1 FOR UPDATE OF s SKIP LOCKED;
    IF v_state.integration_id IS NULL THEN RETURN; END IF;

    -- A crashed worker never completed/failed its run; the next claimant
    -- abandons it before starting a new generation, so at most one `running`
    -- row survives per integration.
    UPDATE public.email_sync_runs
    SET status = 'abandoned', completed_at = now()
    WHERE integration_id = v_state.integration_id AND status = 'running';

    v_kind := CASE WHEN v_state.last_success_at IS NULL THEN 'initial' ELSE 'incremental' END;
    v_generation := v_state.lease_generation + 1;
    INSERT INTO public.email_sync_runs (integration_id, user_id, provider, run_kind, status, lease_generation)
    VALUES (v_state.integration_id, v_state.user_id, v_state.provider, v_kind, 'running', v_generation)
    RETURNING id INTO v_run_id;
    UPDATE public.email_sync_state SET lease_owner = p_worker_id,
        lease_generation = v_generation,
        lease_expires_at = now() + make_interval(secs => greatest(p_lease_seconds, 1)),
        last_started_at = now(), updated_at = now()
    WHERE email_sync_state.integration_id = v_state.integration_id;
    RETURN QUERY SELECT v_state.integration_id, v_state.user_id, v_state.provider,
        v_run_id, v_kind, v_generation, now() + make_interval(secs => greatest(p_lease_seconds, 1));
END; $$;

DROP FUNCTION IF EXISTS public.claim_due_email_reconciliation(text, integer);
CREATE FUNCTION public.claim_due_email_reconciliation(p_worker_id text, p_lease_seconds integer)
RETURNS TABLE (integration_id uuid, user_id uuid, provider text, run_id uuid,
               run_kind text, lease_generation bigint, lease_expires_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_state public.email_sync_state; v_run_id uuid; v_kind text; v_generation bigint;
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

    UPDATE public.email_sync_runs
    SET status = 'abandoned', completed_at = now()
    WHERE integration_id = v_state.integration_id AND status = 'running';

    v_kind := CASE WHEN v_state.last_reconciled_at IS NOT NULL
                        AND v_state.last_reconciled_at <= now() - interval '7 days'
                   THEN 'weekly_reconcile' ELSE 'daily_reconcile' END;
    v_generation := v_state.lease_generation + 1;
    INSERT INTO public.email_sync_runs (integration_id, user_id, provider, run_kind, status, lease_generation)
    VALUES (v_state.integration_id, v_state.user_id, v_state.provider, v_kind, 'running', v_generation)
    RETURNING id INTO v_run_id;
    UPDATE public.email_sync_state SET lease_owner = p_worker_id,
        lease_generation = v_generation,
        lease_expires_at = now() + make_interval(secs => greatest(p_lease_seconds, 1)),
        last_started_at = now(), updated_at = now()
    WHERE email_sync_state.integration_id = v_state.integration_id;
    RETURN QUERY SELECT v_state.integration_id, v_state.user_id, v_state.provider,
        v_run_id, v_kind, v_generation, now() + make_interval(secs => greatest(p_lease_seconds, 1));
END; $$;

DROP FUNCTION IF EXISTS public.heartbeat_email_sync(uuid, text, integer);
CREATE FUNCTION public.heartbeat_email_sync(p_integration_id uuid, p_worker_id text, p_generation bigint, p_lease_seconds integer)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    UPDATE public.email_sync_state SET lease_expires_at = now() + make_interval(secs => greatest(p_lease_seconds, 1)), updated_at = now()
    WHERE integration_id = p_integration_id AND lease_owner = p_worker_id
      AND lease_generation = p_generation AND lease_expires_at > now();
    RETURN FOUND;
END; $$;

-- Ownership is verified by the row count of the state UPDATE itself (not a
-- preceding EXISTS check) so there is no window between checking and acting
-- in which a concurrent reclaim could invalidate the check: a stale caller's
-- WHERE predicate simply matches zero rows in the one statement that matters.
DROP FUNCTION IF EXISTS public.complete_email_sync(uuid, uuid, text, integer, boolean);
CREATE FUNCTION public.complete_email_sync(
    p_integration_id uuid, p_run_id uuid, p_worker_id text, p_generation bigint,
    p_poll_interval_seconds integer DEFAULT 300, p_reconciled boolean DEFAULT false)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_updated integer;
BEGIN
    UPDATE public.email_sync_state SET lease_owner = NULL, lease_expires_at = NULL,
        last_discovery_at = now(), last_success_at = now(),
        last_reconciled_at = CASE WHEN p_reconciled THEN now() ELSE last_reconciled_at END,
        consecutive_failures = 0, last_error_code = NULL, last_error_at = NULL,
        next_poll_at = now() + make_interval(secs => greatest(p_poll_interval_seconds, 1)), updated_at = now()
    WHERE integration_id = p_integration_id AND lease_owner = p_worker_id
      AND lease_generation = p_generation AND lease_expires_at > now();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated = 0 THEN RETURN false; END IF;
    UPDATE public.email_sync_runs SET status = 'completed', completed_at = now()
    WHERE id = p_run_id AND integration_id = p_integration_id AND status = 'running'
      AND lease_generation = p_generation;
    RETURN true;
END; $$;

DROP FUNCTION IF EXISTS public.fail_email_sync(uuid, uuid, text, text, text, integer, integer, boolean);
CREATE FUNCTION public.fail_email_sync(
    p_integration_id uuid, p_run_id uuid, p_worker_id text, p_generation bigint, p_error_code text,
    p_error_detail text DEFAULT NULL, p_retry_base_seconds integer DEFAULT 60,
    p_retry_max_seconds integer DEFAULT 1800, p_auth_failure boolean DEFAULT false)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_failures integer; v_delay integer;
BEGIN
    -- Locks and verifies ownership atomically: no separate EXISTS check that
    -- a concurrent reclaim could race between checking and acting.
    SELECT consecutive_failures + 1 INTO v_failures FROM public.email_sync_state
    WHERE integration_id = p_integration_id AND lease_owner = p_worker_id
      AND lease_generation = p_generation
    FOR UPDATE;
    IF NOT FOUND THEN RETURN false; END IF;
    v_delay := LEAST(p_retry_max_seconds, GREATEST(p_retry_base_seconds, 1) * power(2, LEAST(v_failures - 1, 5))::integer);
    UPDATE public.email_sync_runs SET status = 'failed', completed_at = now(), error_code = left(p_error_code, 100), error_detail = left(p_error_detail, 500)
    WHERE id = p_run_id AND integration_id = p_integration_id AND status = 'running' AND lease_generation = p_generation;
    UPDATE public.email_sync_state SET lease_owner = NULL, lease_expires_at = NULL, consecutive_failures = v_failures,
        last_error_code = left(p_error_code, 100), last_error_at = now(), next_poll_at = now() + make_interval(secs => v_delay), updated_at = now()
    WHERE integration_id = p_integration_id AND lease_owner = p_worker_id AND lease_generation = p_generation;
    IF p_auth_failure THEN UPDATE public.integrations SET status = 'expired', updated_at = now() WHERE id = p_integration_id; END IF;
    RETURN true;
END; $$;

REVOKE ALL ON FUNCTION public.claim_due_email_sync(text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_due_email_reconciliation(text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.heartbeat_email_sync(uuid, text, bigint, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.complete_email_sync(uuid, uuid, text, bigint, integer, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.fail_email_sync(uuid, uuid, text, bigint, text, text, integer, integer, boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claim_due_email_sync(text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_due_email_reconciliation(text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.heartbeat_email_sync(uuid, text, bigint, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.complete_email_sync(uuid, uuid, text, bigint, integer, boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.fail_email_sync(uuid, uuid, text, bigint, text, text, integer, integer, boolean) TO service_role;

COMMENT ON FUNCTION public.claim_due_email_sync(text, integer)
    IS 'Generation-fenced provider discovery claim; abandons any prior running run for the integration first';
COMMENT ON FUNCTION public.claim_due_email_reconciliation(text, integer)
    IS 'Generation-fenced reconciliation claim; abandons any prior running run for the integration first';

-- ---------------------------------------------------------------------------
-- 4. One counted health RPC, predicates pinned to the claim RPCs above.
-- ---------------------------------------------------------------------------

DROP FUNCTION IF EXISTS public.health_dead_letter_counts();
DROP FUNCTION IF EXISTS public.health_poll_slo(integer);

CREATE FUNCTION public.health_work_state(p_warning_seconds integer)
RETURNS TABLE (
    status text,
    ready_emails integer,
    processing_emails integer,
    stale_processing_emails integer,
    unclaimable_emails integer,
    stale_sync_runs integer,
    items_pending integer,
    items_dead_letter integer,
    attachments_dead_letter integer,
    integrations_due integer,
    leases_held integer,
    oldest_next_poll_seconds integer,
    open_incidents integer
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_ready integer;
    v_processing integer;
    v_stale_processing integer;
    v_unclaimable integer;
    v_stale_sync_runs integer;
    v_items_pending integer;
    v_items_dead_letter integer;
    v_attachments_dead_letter integer;
    v_integrations_due integer;
    v_leases_held integer;
    v_oldest_next_poll_seconds integer;
    v_open_incidents integer;
    v_status text;
BEGIN
    -- Mirrors claim_unprocessed_email's pending-claim predicate exactly.
    SELECT count(*)::int INTO v_ready
    FROM public.emails e
    WHERE e.processing_status = 'pending'
      AND e.attempts < e.max_attempts
      AND (e.locked_until IS NULL OR e.locked_until < now())
      AND (e.next_retry_at IS NULL OR e.next_retry_at <= now())
      AND NOT EXISTS (
          SELECT 1 FROM public.attachments a
          WHERE a.email_id = e.id AND a.ingestion_status IN ('pending', 'processing', 'retry')
      );

    SELECT count(*)::int INTO v_processing FROM public.emails WHERE processing_status = 'processing';

    SELECT count(*)::int INTO v_stale_processing
    FROM public.emails
    WHERE processing_status = 'processing'
      AND (locked_until IS NULL OR locked_until < now());

    -- A row the claim RPC will never pick up again without operator action:
    -- terminally failed and dead-lettered, or a legacy pending row that still
    -- violates the claimability invariant despite the migration backfill.
    SELECT count(*)::int INTO v_unclaimable
    FROM public.emails
    WHERE processing_status = 'failed'
       OR (processing_status = 'pending' AND attempts >= max_attempts);

    SELECT count(*)::int INTO v_stale_sync_runs
    FROM public.email_sync_runs r
    JOIN public.email_sync_state s ON s.integration_id = r.integration_id
    WHERE r.status = 'running'
      AND (s.lease_expires_at IS NULL OR s.lease_expires_at < now());

    SELECT count(*)::int INTO v_items_dead_letter FROM public.email_ingestion_items WHERE acquisition_status = 'dead_letter';
    SELECT count(*)::int INTO v_items_pending FROM public.email_ingestion_items WHERE acquisition_status IN ('pending', 'retry', 'processing');
    SELECT count(*)::int INTO v_attachments_dead_letter FROM public.attachments WHERE ingestion_status = 'dead_letter';

    SELECT count(*)::int INTO v_integrations_due
    FROM public.email_sync_state s
    JOIN public.integrations i ON i.id = s.integration_id
    WHERE i.status = 'active' AND s.next_poll_at <= now()
      AND (s.lease_expires_at IS NULL OR s.lease_expires_at <= now());

    SELECT count(*)::int INTO v_leases_held FROM public.email_sync_state WHERE lease_expires_at > now();

    SELECT CASE WHEN min(s.next_poll_at) IS NULL THEN NULL
                ELSE GREATEST(0, EXTRACT(EPOCH FROM (now() - min(s.next_poll_at)))::int) END
    INTO v_oldest_next_poll_seconds
    FROM public.email_sync_state s;

    SELECT count(*)::int INTO v_open_incidents
    FROM public.operational_incidents
    WHERE status = 'open' AND incident_key LIKE 'email-sync:%';

    v_status := CASE WHEN v_stale_processing > 0
                       OR v_unclaimable > 0
                       OR v_stale_sync_runs > 0
                       OR v_items_dead_letter > 0
                       OR v_attachments_dead_letter > 0
                       OR v_open_incidents > 0
                       OR (v_oldest_next_poll_seconds IS NOT NULL AND v_oldest_next_poll_seconds > p_warning_seconds)
                  THEN 'degraded' ELSE 'ok' END;

    RETURN QUERY SELECT v_status, v_ready, v_processing, v_stale_processing, v_unclaimable,
        v_stale_sync_runs, v_items_pending, v_items_dead_letter, v_attachments_dead_letter,
        v_integrations_due, v_leases_held, v_oldest_next_poll_seconds, v_open_incidents;
END; $$;

REVOKE ALL ON FUNCTION public.health_work_state(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.health_work_state(integer) TO service_role;
COMMENT ON FUNCTION public.health_work_state(integer)
    IS 'S1.4: one counted health RPC; ready/stale/unclaimable predicates are pinned to the claim RPCs in test_schema_contract.py';
