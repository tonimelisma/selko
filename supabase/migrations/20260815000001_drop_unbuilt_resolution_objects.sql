-- G1: remove the unbuilt R2/R3 resolution and identity schema.
-- These objects were never deployed to production. Refuse to drop them if
-- anything has been written locally or in staging so an operator must stop
-- and perform a hand-reviewed forward repair instead.

DO $$
DECLARE
    v_count bigint;
BEGIN
    SELECT count(*) INTO v_count FROM public.email_event_resolutions;
    IF v_count > 0 THEN
        RAISE EXCEPTION
            'email_event_resolutions holds % rows; stop and hand-review before dropping',
            v_count;
    END IF;

    SELECT count(*) INTO v_count FROM public.email_calendar_components;
    IF v_count > 0 THEN
        RAISE EXCEPTION
            'email_calendar_components holds % rows; stop and hand-review before dropping',
            v_count;
    END IF;

    SELECT count(*) INTO v_count FROM public.event_identity_hints;
    IF v_count > 0 THEN
        RAISE EXCEPTION
            'event_identity_hints holds % rows; stop and hand-review before dropping',
            v_count;
    END IF;

    SELECT count(*) INTO v_count
    FROM public.emails
    WHERE processing_status = 'resolving';
    IF v_count > 0 THEN
        RAISE EXCEPTION '% emails are in resolving; drain before dropping', v_count;
    END IF;
END $$;

DROP FUNCTION IF EXISTS public.commit_email_event_resolution_item(uuid, uuid, integer, text, bigint, uuid, text);
DROP FUNCTION IF EXISTS public.fail_email_event_resolution(uuid, uuid, text, bigint, text, integer);
DROP FUNCTION IF EXISTS public.heartbeat_email_event_resolution(uuid, uuid, text, bigint, integer);
DROP FUNCTION IF EXISTS public.claim_email_event_resolution(text, integer);
DROP FUNCTION IF EXISTS public.enqueue_email_event_resolution(uuid, uuid, jsonb, text, text, text);

DROP TRIGGER IF EXISTS trg_ensure_event_resolution_lane ON public.users;
DROP FUNCTION IF EXISTS public.ensure_event_resolution_lane();

DROP TABLE IF EXISTS public.event_resolution_lanes;
DROP TABLE IF EXISTS public.email_event_resolution_items;
DROP TABLE IF EXISTS public.email_event_resolutions;
DROP TABLE IF EXISTS public.event_identity_hints;
DROP TABLE IF EXISTS public.email_calendar_components;

-- There is no producer for 'resolving' once the unbuilt resolution objects are
-- gone. Preserve the repaired status domain, including 'skipped'.
ALTER TABLE public.emails DROP CONSTRAINT IF EXISTS emails_processing_status_check;
ALTER TABLE public.emails ADD CONSTRAINT emails_processing_status_check
    CHECK (processing_status IN ('pending', 'processing', 'processed', 'failed', 'skipped'));

-- R3 replaced the live three-argument RPC with a four-argument overload. Drop
-- both overloads first so exactly one callable function remains.
DROP FUNCTION IF EXISTS public.save_email_with_attachment_descriptors(uuid, jsonb, jsonb, jsonb);
DROP FUNCTION IF EXISTS public.save_email_with_attachment_descriptors(uuid, jsonb, jsonb);
CREATE FUNCTION public.save_email_with_attachment_descriptors(
    p_user_id uuid,
    p_email jsonb,
    p_descriptors jsonb
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_email_id uuid;
    v_email jsonb := p_email || jsonb_build_object('user_id', p_user_id);
    v_payload_cols text[] := ARRAY(
        SELECT quote_ident(k)
        FROM jsonb_object_keys(v_email) AS k
        WHERE k IN (
            'user_id', 'email_provider', 'provider_message_id', 'thread_id',
            'subject', 'from_email', 'from_name', 'to_emails', 'date_sent',
            'snippet', 'provider_labels', 'has_attachments', 'body_text',
            'is_calendar_invite', 'integration_id', 'provider_folder_ids',
            'content_hash'
        )
    );
    v_conflict_cols text[] := ARRAY['"user_id"', '"email_provider"', '"provider_message_id"'];
    v_set_cols text[] := ARRAY(
        SELECT quote_ident(k) || ' = EXCLUDED.' || quote_ident(k)
        FROM unnest(v_payload_cols) AS k
        WHERE k <> ALL(v_conflict_cols)
    );
    v_insert_cols text := array_to_string(v_payload_cols, ', ');
    v_set_clause text := array_to_string(v_set_cols, ', ');
    v_sql text;
BEGIN
    IF NOT (v_email ? 'user_id' AND v_email ? 'email_provider' AND v_email ? 'provider_message_id') THEN
        RAISE EXCEPTION 'p_email must include user_id, email_provider and provider_message_id';
    END IF;

    IF v_insert_cols = '' OR v_set_clause = '' THEN
        RAISE EXCEPTION 'save_email_with_attachment_descriptors: no settable columns resolved from p_email';
    END IF;

    v_sql := format(
        'INSERT INTO public.emails (%s) SELECT %s FROM jsonb_populate_record(NULL::public.emails, $1) '
        'ON CONFLICT (user_id, email_provider, provider_message_id) DO UPDATE SET %s '
        'RETURNING id',
        v_insert_cols, v_insert_cols, v_set_clause
    );
    EXECUTE v_sql USING v_email INTO v_email_id;

    INSERT INTO public.attachments
        (user_id, email_id, provider_attachment_id, filename, mime_type, size_bytes, ingestion_status)
    SELECT
        p_user_id,
        v_email_id,
        d->>'provider_attachment_id',
        COALESCE(NULLIF(d->>'filename', ''), NULLIF(d->>'name', ''), 'unnamed'),
        COALESCE(NULLIF(d->>'mime_type', ''), NULLIF(d->>'contentType', ''), 'application/octet-stream'),
        COALESCE(NULLIF(d->>'size_bytes', '')::bigint, NULLIF(d->>'size', '')::bigint, 0),
        'pending'
    FROM jsonb_array_elements(COALESCE(p_descriptors, '[]'::jsonb)) AS d
    WHERE d->>'provider_attachment_id' IS NOT NULL
      AND d->>'provider_attachment_id' <> ''
    ON CONFLICT (email_id, provider_attachment_id)
        WHERE provider_attachment_id IS NOT NULL AND provider_attachment_id <> ''
        DO NOTHING;

    RETURN v_email_id;
END; $$;

REVOKE ALL ON FUNCTION public.save_email_with_attachment_descriptors(uuid, jsonb, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.save_email_with_attachment_descriptors(uuid, jsonb, jsonb) TO service_role;
