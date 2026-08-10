-- Fix: remove invented backup table that was created without RLS
-- 20260809000001 created public.emails_body_html_backup without ENABLE ROW LEVEL SECURITY,
-- leaving a public table with email bodies and advisor warning "RLS has not been enabled".
-- No rollback was requested; per owner direction this backup is not needed.
-- Drop it entirely to close the security gap.
DROP TABLE IF EXISTS public.emails_body_html_backup;
