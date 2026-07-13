-- Fix-forward hardening for reliable email ingestion and History.

ALTER TABLE public.emails
    DROP CONSTRAINT IF EXISTS emails_processing_outcome_check;

ALTER TABLE public.emails
    ADD CONSTRAINT emails_processing_outcome_check
    CHECK (processing_outcome IS NULL OR processing_outcome IN (
        'no_event',
        'event_matched',
        'event_created',
        'event_updated',
        'event_created_and_updated',
        'event_cancelled'
    ));

ALTER TABLE public.email_folders
    ADD COLUMN IF NOT EXISTS is_scannable boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS is_permanently_excluded boolean NOT NULL DEFAULT false;

DROP INDEX IF EXISTS idx_email_folders_syncable;
CREATE INDEX idx_email_folders_syncable
    ON public.email_folders (integration_id, is_included, is_scannable);

-- PR183 could not identify Graph system folders when Graph omitted wellKnownName,
-- so its Outlook system rows were not safe to retain. They are rediscovered with
-- immutable IDs by the fix-forward worker.
DELETE FROM public.email_folders
WHERE provider = 'outlook'
  AND is_system = true;

DROP POLICY IF EXISTS "Users can update own email folder preferences"
    ON public.email_folders;
REVOKE UPDATE ON TABLE public.email_folders FROM authenticated;

CREATE OR REPLACE FUNCTION public.set_email_folder_preference(
    p_folder_id uuid,
    p_is_included boolean
)
RETURNS SETOF public.email_folders
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF auth.uid() IS NULL THEN
        RAISE EXCEPTION 'Authentication required';
    END IF;

    RETURN QUERY
    UPDATE public.email_folders
    SET is_included = p_is_included,
        user_override = true,
        sync_cursor = NULL,
        updated_at = now()
    WHERE id = p_folder_id
      AND user_id = auth.uid()
      AND is_system = false
      AND is_permanently_excluded = false
      AND provider IN ('gmail', 'outlook')
    RETURNING *;
END;
$$;

REVOKE ALL ON FUNCTION public.set_email_folder_preference(uuid, boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.set_email_folder_preference(uuid, boolean)
    TO authenticated, service_role;

CREATE OR REPLACE FUNCTION public.reconcile_outlook_email_folders(
    p_integration_id uuid,
    p_forbidden_folder_ids text[] DEFAULT '{}'
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_count integer;
BEGIN
    DELETE FROM public.email_folders
    WHERE integration_id = p_integration_id
      AND provider = 'outlook'
      AND (
          is_permanently_excluded = true
          OR provider_folder_id = ANY(COALESCE(p_forbidden_folder_ids, '{}'))
      );
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;

REVOKE ALL ON FUNCTION public.reconcile_outlook_email_folders(uuid, text[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.reconcile_outlook_email_folders(uuid, text[])
    TO service_role;

COMMENT ON COLUMN public.email_folders.is_scannable IS
    'Whether the worker may issue provider listing/delta/message requests for this row.';
COMMENT ON COLUMN public.email_folders.is_permanently_excluded IS
    'Provider-owned or hidden system tree that is never user-configurable or scanned.';

