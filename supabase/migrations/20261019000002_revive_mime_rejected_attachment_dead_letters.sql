-- Revive attachments dead-lettered by the bucket MIME allowlist gap.
--
-- `20261019000001` closed the gap between the worker's accept-set and the
-- attachments bucket allowlist, but a row already in `dead_letter` is never
-- reclaimed: `claim_email_attachment` requires `attempts < max_attempts`, and
-- the rejected rows sit at 8/8. The fix alone therefore leaves them stranded
-- and `attachments_dead_letter` non-zero — one of the four counts
-- assert-health.sh calls never acceptable, which keeps /health degraded and
-- which no worker clears.
--
-- Production currently holds exactly one such row: `farewell-slack-dms.md`,
-- `text/markdown`, attempts 8/8, `ingestion_error_code = 'unknown'`, created
-- 2026-10-18T23:14:20Z. It was rejected with `415 invalid_mime_type` (the
-- generic error code is why it reads as `unknown`), so the bytes were never
-- stored and the attachment has never reached the user.
--
-- Same posture as `20260812000002_revive_database_transient_dead_letters.sql`
-- and `20260803000001_revive_misclassified_dead_letters.sql`: reset to
-- `pending` with `attempts = 0` so the next acquisition poll re-attempts it
-- against the corrected allowlist. If the provider attachment has since
-- disappeared, `acquire_attachment` classifies it `unsupported` on its own.
--
-- Scoped deliberately:
--
--   * `ingestion_status = 'dead_letter'` and `attempts >= max_attempts` — only
--     stranded rows, not the live retry cohort.
--   * `ingestion_error_code = 'unknown'` — the generic code a storage
--     rejection produced. A row that dead-lettered with a typed code failed
--     for a reason this migration does not fix, so it is left alone.
--   * the MIME must be one the bucket now accepts — otherwise reviving it
--     just walks it back to dead_letter and the gauge returns. Any `text/*`
--     or `image/*` subtype now qualifies, plus `application/rtf`, which was
--     the second gap `20261019000001` closed.
--
-- Idempotent: a second run matches nothing. After this, the health sweeper
-- resolves the `attachment_dead_letter` incident once no dead letters remain,
-- the same way it resolved the `acquisition_dead_letter` one in August.

UPDATE public.attachments
SET ingestion_status = 'pending',
    attempts = 0,
    next_retry_at = NULL,
    ingestion_error_code = NULL,
    locked_by = NULL,
    locked_until = NULL
WHERE ingestion_status = 'dead_letter'
  AND attempts >= max_attempts
  AND ingestion_error_code = 'unknown'
  AND (
      mime_type LIKE 'text/%'
      OR mime_type LIKE 'image/%'
      OR mime_type IN (
          'application/pdf',
          'application/rtf',
          'application/ics',
          'application/msword',
          'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          'application/vnd.ms-excel',
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          'application/vnd.ms-powerpoint',
          'application/vnd.openxmlformats-officedocument.presentationml.presentation'
      )
  );
