-- Fix save_email_with_attachment_descriptors: combine both prior fixes
-- 20260809000001 correctly removed body_html from the allowed column list (the
-- column was dropped), but broke attachments (file_name/file_size vs filename/size_bytes).
-- 20260811000004 repaired attachments by copying 20260803000002 verbatim, which
-- re-introduced body_html into the allowed list. Any payload with body_html
-- (e.g. Outlook's parse_outlook_message sets body_html=None) now raises
-- 'column "body_html" of relation "emails" does not exist' on every Outlook
-- acquisition, while Gmail (which never sets body_html) succeeds.
-- This migration keeps the repaired attachment logic and restores the
-- body_html exclusion from 20260809000001.

CREATE OR REPLACE FUNCTION public.save_email_with_attachment_descriptors(
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
            'user_id','email_provider','provider_message_id','thread_id',
            'subject','from_email','from_name','to_emails','date_sent',
            'snippet','provider_labels','has_attachments','body_text',
            'is_calendar_invite','integration_id',
            'provider_folder_ids','content_hash'
        )
    );
    v_conflict_cols text[] := ARRAY['"user_id"','"email_provider"','"provider_message_id"'];
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
    WHERE d->>'provider_attachment_id' IS NOT NULL AND d->>'provider_attachment_id' <> ''
    ON CONFLICT (email_id, provider_attachment_id)
        WHERE provider_attachment_id IS NOT NULL AND provider_attachment_id <> ''
        DO NOTHING;

    RETURN v_email_id;
END; $$;

REVOKE ALL ON FUNCTION public.save_email_with_attachment_descriptors(uuid, jsonb, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.save_email_with_attachment_descriptors(uuid, jsonb, jsonb) TO service_role;

COMMENT ON FUNCTION public.save_email_with_attachment_descriptors(uuid, jsonb, jsonb) IS
    'Fix: body_html excluded (column dropped in 20260809000001) and attachment descriptors repaired (filename/size_bytes) — combines both prior fixes';
