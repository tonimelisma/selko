-- Make the attachments bucket accept everything the worker will try to upload.
--
-- Two allowlists decide whether an attachment can be stored, and they were
-- maintained independently:
--
--   the worker  `SUPPORTED_ATTACHMENT_MIME_PREFIXES = ("image/", "text/")`
--               plus ten explicit application/* types
--               (backend/selko/workers/email_ingestion.py)
--   the bucket  twenty-one enumerated types, no wildcards
--
-- Anything the worker accepts but the bucket does not is a guaranteed failure:
-- `acquire_attachment` downloads the bytes, `upload_to_storage` gets
-- `415 invalid_mime_type`, the generic `AttachmentError` classifies as
-- `unknown` (retryable), and the row burns all 8 attempts and dead-letters.
-- `attachments_dead_letter = 0` is one of the four invariants
-- assert-health.sh calls NEVER acceptable, and a dead_letter row does not
-- clear itself, so one such attachment pins /health to degraded permanently.
--
-- That is what happened on 2026-10-18: a `text/markdown` attachment
-- ("farewell-slack-dms.md") matched the worker's `text/` prefix, was rejected
-- by the bucket, retried 8 times and dead-lettered, which turned the
-- production health check red right after the ingestion-stall deploy drained
-- 19 days of backlog. Reproduced locally: with the old allowlist the upload
-- returns `415 invalid_mime_type "mime type text/markdown is not supported"`.
--
-- 20260728000001 hit the same class and fixed it by adding the three types
-- that had been seen ('text/calendar', 'application/ics',
-- 'application/vnd.google-apps.document'). That treats the symptom: the sets
-- still drift, and the next unlisted `text/*` or `image/*` subtype
-- dead-letters the same way. Comparing them now also turns up a second live
-- gap nobody had hit yet -- the worker accepts `application/rtf` and the
-- bucket did not.
--
-- Supabase Storage honours wildcard entries (verified against a real bucket:
-- with `text/*` set, `text/markdown` and `text/plain` upload and `image/png`
-- is still correctly refused), so the bucket can mirror the worker's prefixes
-- exactly instead of chasing subtypes. backend/tests/integration/
-- test_integration_attachment_mime_contract.py pins the two sets together so
-- they cannot drift again.
--
-- This is a strict superset of the previous allowlist: every type it listed is
-- either repeated below or subsumed by `image/*` / `text/*`. Nothing that
-- could be stored before is refused now.

update storage.buckets
set allowed_mime_types = array[
    -- Mirrors SUPPORTED_ATTACHMENT_MIME_PREFIXES. Covers text/plain,
    -- text/csv, text/html and text/calendar from the old list, and the
    -- text/markdown that started this.
    'image/*',
    'text/*',
    -- Mirrors SUPPORTED_ATTACHMENT_MIMES. 'application/rtf' is the one the
    -- worker accepted and the bucket did not.
    'application/pdf',
    'application/rtf',
    'application/ics',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    -- Already allowed before this migration and kept so nothing that could be
    -- stored becomes unstorable. The worker's gate marks these `unsupported`
    -- and never uploads them, but `process_attachment` in
    -- services/attachments.py also calls upload_to_storage and is not behind
    -- that gate.
    'application/octet-stream',
    'application/zip',
    'application/x-zip-compressed',
    'application/vnd.google-apps.document'
]::text[]
where id = 'attachments';
