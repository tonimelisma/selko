-- Auto-provision durable sync state for email integrations.
--
-- 20260801000001 backfilled email_sync_state for integrations that existed at
-- migration time, but nothing created a row afterwards. Because
-- claim_due_email_sync only ever selects from email_sync_state, a newly
-- connected Gmail or Outlook account would never be polled at all — v2 would
-- silently ingest nothing for every new user.
--
-- A trigger is used rather than application code so the guarantee holds no
-- matter which path writes the integration (OAuth callback, CLI, backfill, or
-- a manual fix-up).

CREATE OR REPLACE FUNCTION public.ensure_email_sync_state()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF NEW.provider::text NOT IN ('gmail', 'outlook') THEN
        RETURN NEW;
    END IF;
    IF NEW.status <> 'active' THEN
        RETURN NEW;
    END IF;

    INSERT INTO public.email_sync_state (
        integration_id, user_id, provider, initial_watermark_at, next_poll_at
    )
    VALUES (
        NEW.id, NEW.user_id, NEW.provider::text, now() - interval '14 days', now()
    )
    ON CONFLICT (integration_id) DO UPDATE SET
        -- Reconnecting after an expiry must resume promptly rather than wait
        -- out the backoff the failures accumulated, but never rewind a lease
        -- that a worker currently holds.
        next_poll_at = CASE
            WHEN public.email_sync_state.lease_expires_at IS NULL
              OR public.email_sync_state.lease_expires_at <= now()
            THEN now()
            ELSE public.email_sync_state.next_poll_at
        END,
        consecutive_failures = 0,
        last_error_code = NULL,
        updated_at = now();

    RETURN NEW;
END; $$;

DROP TRIGGER IF EXISTS integrations_ensure_email_sync_state ON public.integrations;
CREATE TRIGGER integrations_ensure_email_sync_state
    AFTER INSERT OR UPDATE OF status, provider ON public.integrations
    FOR EACH ROW EXECUTE FUNCTION public.ensure_email_sync_state();

-- Cover any integration created between 20260801000001 and this migration.
INSERT INTO public.email_sync_state (integration_id, user_id, provider, initial_watermark_at)
SELECT i.id, i.user_id, i.provider::text, now() - interval '14 days'
FROM public.integrations i
WHERE i.provider::text IN ('gmail', 'outlook') AND i.status = 'active'
ON CONFLICT (integration_id) DO NOTHING;

-- Ask the coordinator to pick an integration up on its next tick. Used when a
-- folder is newly included, replacing the legacy email_fetch scheduled task.
CREATE OR REPLACE FUNCTION public.request_email_sync_now(p_integration_id uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_updated integer;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.integrations i
        WHERE i.id = p_integration_id AND i.user_id = auth.uid()
    ) THEN
        RETURN false;
    END IF;

    UPDATE public.email_sync_state s
    SET next_poll_at = now(), updated_at = now()
    WHERE s.integration_id = p_integration_id
      AND (s.lease_expires_at IS NULL OR s.lease_expires_at <= now());
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated > 0;
END; $$;

REVOKE ALL ON FUNCTION public.request_email_sync_now(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.request_email_sync_now(uuid) TO authenticated, service_role;

COMMENT ON FUNCTION public.ensure_email_sync_state IS
    'Creates or revives email_sync_state whenever an email integration becomes active';
COMMENT ON FUNCTION public.request_email_sync_now IS
    'Caller-owned request to poll an integration on the next coordinator tick';

-- The scheduled_tasks CHECK still only permitted 'email_fetch', the task type
-- the durable poller replaces. photo_fetch is enqueued by
-- workers/photo_fetch.py but would have been rejected by this constraint, so
-- widen it to the type that remains and drop the one that no longer exists.
-- Existing email_fetch rows are historical; delete the ones that can never run.
DELETE FROM public.scheduled_tasks
WHERE task_type = 'email_fetch' AND status IN ('pending', 'processing');

ALTER TABLE public.scheduled_tasks
    DROP CONSTRAINT IF EXISTS scheduled_tasks_task_type_check;
ALTER TABLE public.scheduled_tasks
    ADD CONSTRAINT scheduled_tasks_task_type_check
    CHECK (task_type IN ('photo_fetch', 'email_fetch'));

COMMENT ON COLUMN public.scheduled_tasks.task_type IS
    'photo_fetch is the only type still produced; email_fetch is retained for historical rows';
