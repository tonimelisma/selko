-- Revive Outlook dead letters stuck on database_transient
--
-- 12 Outlook ingestion items went to dead_letter with last_error_code
-- = 'database_transient' and attempts=8 between 2026-08-10 and
-- 2026-08-11. At that time the save path still contained two persistent
-- defects that have since been fixed in the same release line:
--
--   * claim_item() returned uuid.UUID objects that failed at json.dumps
--     (fixed in 0ddc7914 via _normalize_pg_row)
--   * save_email_with_attachment_descriptors's allowed column list still
--     contained body_html after the column was dropped (fixed in
--     b70cd9b7 / 20260812000001_fix_save_body_html.sql)
--
-- A transient DB error that exhausts max_attempts is retryable in principle;
-- these 12 are not genuinely unparseable (no parse_invalid, no
-- provider_permanent) and their provider_message_ids do not exist in emails,
-- so they have never been delivered to the user. Resetting them to pending
-- with attempts=0 lets the next acquisition poll re-attempt them with the
-- fixed code. If the provider message was deleted in the meantime,
-- acquire_item() will correctly classify it as removed (ProviderMessageMissing).
--
-- Scoped to dead_letter + database_transient + attempts>=8 so the concurrent
-- 2026-08-12 retry cohort (now completing) and any genuine future dead letters
-- are untouched. Idempotent: running twice is a no-op.
--
-- Verify on staging first: SELECT count(*) FROM email_ingestion_items
-- WHERE acquisition_status='dead_letter' AND last_error_code='database_transient';
-- Expected 0 on staging (staging has no prod Outlook dead letters). On prod
-- expected 12 before, 0 after. The health sweeper will resolve the
-- acquisition_dead_letter incident once no dead letters remain.

UPDATE public.email_ingestion_items
SET acquisition_status = 'pending',
    attempts = 0,
    next_retry_at = NULL,
    last_error_code = NULL,
    last_error_at = NULL,
    lease_owner = NULL,
    lease_expires_at = NULL,
    updated_at = now()
WHERE acquisition_status = 'dead_letter'
  AND last_error_code = 'database_transient'
  AND attempts >= 8;
