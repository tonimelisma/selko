-- Fix emails_processing_status_check regression from R2: restored 'resolving' but dropped 'skipped'
-- Original 20260126 allowed ('pending','processing','processed','failed','skipped')
-- R2 20260813000001 replaced with ('pending','processing','resolving','processed','failed')
-- Breaking mark_email_status(..., "skipped") for sender_ignored / calendar_invite
ALTER TABLE public.emails DROP CONSTRAINT IF EXISTS emails_processing_status_check;
ALTER TABLE public.emails ADD CONSTRAINT emails_processing_status_check
  CHECK (processing_status IN ('pending','processing','resolving','processed','failed','skipped'));
