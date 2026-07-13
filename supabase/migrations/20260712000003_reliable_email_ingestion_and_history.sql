-- Reliable email ingestion state, user-folder preferences, and email history.

ALTER TABLE public.emails
    ADD COLUMN IF NOT EXISTS provider_folder_ids text[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS processing_outcome text,
    ADD COLUMN IF NOT EXISTS processing_explanation text,
    ADD COLUMN IF NOT EXISTS processing_result jsonb,
    ADD COLUMN IF NOT EXISTS email_folder_id uuid;

ALTER TABLE public.emails
    ADD CONSTRAINT emails_processing_outcome_check
    CHECK (processing_outcome IS NULL OR processing_outcome IN (
        'no_event',
        'event_created',
        'event_updated',
        'event_created_and_updated',
        'event_cancelled'
    ));

CREATE INDEX IF NOT EXISTS idx_emails_history
    ON public.emails (user_id, date_sent DESC)
    WHERE processing_status IN ('processed', 'failed');

CREATE TABLE public.email_folders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    integration_id uuid NOT NULL REFERENCES public.integrations(id) ON DELETE CASCADE,
    provider text NOT NULL CHECK (provider IN ('gmail', 'outlook')),
    provider_folder_id text NOT NULL,
    parent_folder_id text,
    name text NOT NULL,
    full_path text NOT NULL,
    folder_kind text NOT NULL CHECK (folder_kind IN ('label', 'folder')),
    is_system boolean NOT NULL DEFAULT false,
    system_kind text,
    classification_decision text NOT NULL DEFAULT 'include'
        CHECK (classification_decision IN ('include', 'exclude', 'uncertain')),
    classification_reason text,
    user_override boolean NOT NULL DEFAULT false,
    is_included boolean NOT NULL DEFAULT true,
    sync_cursor text,
    discovered_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (integration_id, provider_folder_id)
);

ALTER TABLE public.emails
    ADD CONSTRAINT emails_email_folder_id_fkey
    FOREIGN KEY (email_folder_id) REFERENCES public.email_folders(id) ON DELETE SET NULL;

CREATE INDEX idx_email_folders_user_provider
    ON public.email_folders (user_id, provider, full_path);

CREATE INDEX idx_email_folders_syncable
    ON public.email_folders (integration_id, is_included)
    WHERE is_system = false;

ALTER TABLE public.email_folders ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own email folders"
    ON public.email_folders FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can update own email folder preferences"
    ON public.email_folders FOR UPDATE
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id AND is_system = false);

CREATE POLICY "Service role full access to email folders"
    ON public.email_folders FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE OR REPLACE FUNCTION public.reprocess_email(
    p_user_id uuid,
    p_email_id uuid
)
RETURNS SETOF public.emails
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF auth.uid() IS DISTINCT FROM p_user_id AND auth.role() <> 'service_role' THEN
        RAISE EXCEPTION 'Cannot reprocess another user''s email';
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
        attempts = 0
    WHERE id = p_email_id
      AND user_id = p_user_id
      AND processing_status NOT IN ('pending', 'processing')
    RETURNING public.emails.*;
END;
$$;

GRANT EXECUTE ON FUNCTION public.reprocess_email(uuid, uuid) TO authenticated, service_role;

-- Production reconciliation for rows that were successfully processed but retained
-- an error from an earlier failed attempt.
UPDATE public.emails
SET processing_error = NULL
WHERE processing_status = 'processed'
  AND processing_error IS NOT NULL;

COMMENT ON TABLE public.email_folders IS
    'Discovered Gmail labels and Outlook folders with durable classification and sync state';
COMMENT ON COLUMN public.email_folders.classification_decision IS
    'LLM recommendation: exclude only clearly marketing-oriented folders; uncertain is included';
COMMENT ON COLUMN public.email_folders.user_override IS
    'When true, later folder renames do not replace the user decision';
COMMENT ON COLUMN public.emails.provider_folder_ids IS
    'Current provider folder/label membership; used to reconcile Outlook moves without false Trash';

CREATE OR REPLACE FUNCTION public.claim_unprocessed_email(
    p_worker_id text,
    p_lock_duration_seconds integer DEFAULT 300
)
RETURNS SETOF public.emails
LANGUAGE plpgsql
AS $$
DECLARE
    v_email public.emails;
BEGIN
    SELECT * INTO v_email
    FROM public.emails
    WHERE processing_status = 'pending'
      AND attempts < max_attempts
      AND (locked_until IS NULL OR locked_until < now())
      AND (next_retry_at IS NULL OR next_retry_at <= now())
    ORDER BY created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF v_email.id IS NOT NULL THEN
        UPDATE public.emails
        SET processing_status = 'processing',
            processing_error = NULL,
            locked_by = p_worker_id,
            locked_until = now() + (p_lock_duration_seconds || ' seconds')::interval,
            attempts = attempts + 1
        WHERE id = v_email.id
        RETURNING * INTO v_email;
        RETURN NEXT v_email;
    END IF;
END;
$$;

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
      AND locked_until < now();
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;
