-- Revive dead-lettered items misclassified by the pre-fix substring classifier.
--
-- Before this increment, `safe_error_code()` substring-matched the exception
-- message: any error whose text contained the substring "invalid" — including
-- Gmail 401 "Invalid Credentials" and `invalid_grant` refresh failures — was
-- classified as `parse_invalid`. `run_acquisition_once` then marked the item
-- terminal on its FIRST attempt, so it went to `dead_letter` and was never
-- retried — even after the user reconnected, the email never re-entered the
-- pipeline. The structural classifier (backend/selko/services/email_ingestion.py)
-- now keys on exception type and HTTP status, so this no longer happens.
--
-- Scoped to `last_error_code = 'parse_invalid'` specifically so genuine dead
-- letters (truly unparseable payloads, etc.) are untouched. Run against
-- staging first and record the affected row count in the PR body before prod.

UPDATE public.email_ingestion_items
SET acquisition_status = 'pending',
    attempts = 0,
    next_retry_at = NULL,
    last_error_code = NULL,
    last_error_at = NULL,
    updated_at = now()
WHERE acquisition_status = 'dead_letter'
  AND last_error_code = 'parse_invalid';