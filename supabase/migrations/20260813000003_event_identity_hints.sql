-- R3: identity-aware correlation — Workstream C of review-queue-integrity.md
-- Tables: email_calendar_components, event_identity_hints
-- Extends save_email_with_attachment_descriptors to atomically write components

CREATE TABLE public.email_calendar_components (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email_id uuid NOT NULL REFERENCES public.emails(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  component_index integer NOT NULL CHECK (component_index >= 0),
  method text NOT NULL,
  uid_hash text,
  recurrence_id text,
  recurrence_range text,
  sequence integer,
  dtstamp timestamptz,
  component_status text,
  start_datetime timestamptz,
  end_datetime timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (email_id, component_index)
);

ALTER TABLE public.email_calendar_components ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.email_calendar_components FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.email_calendar_components TO service_role;
CREATE INDEX email_calendar_components_email_idx ON public.email_calendar_components (email_id);
CREATE INDEX email_calendar_components_user_idx ON public.email_calendar_components (user_id);

CREATE TABLE public.event_identity_hints (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  event_id uuid NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
  source_email_id uuid REFERENCES public.emails(id) ON DELETE SET NULL,
  kind text NOT NULL CHECK (kind IN ('ical_uid','provider_thread','join_url','management_url')),
  value_hash text NOT NULL,
  recurrence_id text NOT NULL DEFAULT '',
  strength text NOT NULL CHECK (strength IN ('authoritative','supporting')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (event_id, kind, value_hash, recurrence_id)
);

ALTER TABLE public.event_identity_hints ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.event_identity_hints FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.event_identity_hints TO service_role;
CREATE INDEX event_identity_hints_lookup_idx ON public.event_identity_hints (user_id, kind, value_hash, recurrence_id);

-- Extend save_email_with_attachment_descriptors to also write calendar components atomically
-- Drop and recreate with p_calendar_components jsonb param (4th arg, default '[]')
DROP FUNCTION IF EXISTS public.save_email_with_attachment_descriptors(uuid, jsonb, jsonb);
CREATE OR REPLACE FUNCTION public.save_email_with_attachment_descriptors(
    p_user_id uuid,
    p_email jsonb,
    p_descriptors jsonb,
    p_calendar_components jsonb DEFAULT '[]'::jsonb
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
            'body_html','is_calendar_invite','integration_id',
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

    -- Upsert calendar components (idempotent per email_id+component_index)
    DELETE FROM public.email_calendar_components WHERE email_id = v_email_id;
    INSERT INTO public.email_calendar_components
        (email_id, user_id, component_index, method, uid_hash, recurrence_id, recurrence_range, sequence, dtstamp, component_status, start_datetime, end_datetime)
    SELECT
        v_email_id,
        p_user_id,
        (ord - 1),
        COALESCE(c->>'method',''),
        c->>'uid_hash',
        c->>'recurrence_id',
        c->>'recurrence_range',
        NULLIF(c->>'sequence','')::integer,
        NULLIF(c->>'dtstamp','')::timestamptz,
        c->>'component_status',
        NULLIF(c->>'start_datetime','')::timestamptz,
        NULLIF(c->>'end_datetime','')::timestamptz
    FROM jsonb_array_elements(COALESCE(p_calendar_components, '[]'::jsonb)) WITH ORDINALITY AS t(c, ord);

    RETURN v_email_id;
END; $$;

REVOKE ALL ON FUNCTION public.save_email_with_attachment_descriptors(uuid, jsonb, jsonb, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.save_email_with_attachment_descriptors(uuid, jsonb, jsonb, jsonb) TO service_role;

COMMENT ON TABLE public.email_calendar_components IS 'Provider-neutral calendar components per email (R3)';
COMMENT ON TABLE public.event_identity_hints IS 'Normalized identity hints per event (R3)';
