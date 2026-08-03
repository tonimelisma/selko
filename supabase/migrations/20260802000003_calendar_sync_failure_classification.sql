-- Structured calendar sync failure classification (oauth-reconnect-catch-up.md, section 1)
--
-- Adds a constrained failure taxonomy so control flow can distinguish
-- expired-OAuth failures from provider outages instead of string-matching
-- sync_error. Also stops claim_approved_event from burning sync attempts for
-- users whose google_calendar integration is known to be inactive, and
-- narrows the global circuit breaker to failures that are actually about
-- provider health rather than one user's expired token.

ALTER TABLE public.events
    ADD COLUMN IF NOT EXISTS sync_failure_code text;

ALTER TABLE public.events
    ADD CONSTRAINT events_sync_failure_code_check
    CHECK (
        sync_failure_code IS NULL OR sync_failure_code IN (
            'oauth_required',
            'oauth_scope_required',
            'provider_transient',
            'rate_limited',
            'invalid_event',
            'permission_denied',
            'unknown'
        )
    );

COMMENT ON COLUMN public.events.sync_failure_code IS
    'Typed classification of the most recent calendar sync failure. Control flow must branch on this, never on sync_error/dead_letter_reason text.';

-- claim_approved_event now excludes users whose google_calendar integration
-- is not active, so workers stop re-attempting a sync that is known to be
-- blocked on reauthorization until the user reconnects.
CREATE OR REPLACE FUNCTION claim_approved_event(
    p_worker_id text,
    p_lock_duration_seconds integer DEFAULT 300
) RETURNS SETOF events AS $$
DECLARE
    v_event events;
BEGIN
    SELECT * INTO v_event
    FROM events
    WHERE status = 'approved'
      AND sync_attempts < max_sync_attempts
      AND (locked_until IS NULL OR locked_until < now())
      AND (next_retry_at IS NULL OR next_retry_at <= now())
      AND EXISTS (
          SELECT 1 FROM integrations i
          WHERE i.user_id = events.user_id
            AND i.provider = 'google_calendar'
            AND i.status = 'active'
      )
    ORDER BY updated_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF v_event.id IS NOT NULL THEN
        UPDATE events SET
            status = 'syncing',
            locked_by = p_worker_id,
            locked_until = now() + (p_lock_duration_seconds || ' seconds')::interval,
            sync_attempts = sync_attempts + 1
        WHERE id = v_event.id
        RETURNING * INTO v_event;

        RETURN NEXT v_event;
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION claim_approved_event IS 'Atomically claim next approved event for calendar sync (respects next_retry_at; requires an active google_calendar integration)';
