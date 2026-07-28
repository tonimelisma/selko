-- Production email sync encountered provider attachments that are legitimate
-- but were rejected by the attachments bucket MIME allowlist. A rejected
-- attachment aborts the reliable fetch transaction before its cursor advances.
update storage.buckets
set allowed_mime_types = (
    select array_agg(distinct mime)
    from unnest(
        coalesce(allowed_mime_types, array[]::text[]) || array[
            'text/calendar',
            'application/ics',
            'application/vnd.google-apps.document'
        ]::text[]
    ) as mime
)
where id = 'attachments'
  and not (
      coalesce(allowed_mime_types, array[]::text[]) @> array[
          'text/calendar',
          'application/ics',
          'application/vnd.google-apps.document'
      ]::text[]
  );
