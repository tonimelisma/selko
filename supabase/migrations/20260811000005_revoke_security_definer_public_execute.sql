-- Remove the implicit PUBLIC grant from privileged functions discovered by
-- the schema contract test. Existing authenticated and service_role grants
-- remain unchanged.
REVOKE EXECUTE ON FUNCTION public.check_and_increment_quota(uuid, text, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.claim_pending_photo(text, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.claim_unprocessed_email(text, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.ensure_email_sync_state() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_llm_usage_summary(uuid, date, date) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_user_quota_usage(uuid, date) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.handle_new_user() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.notify_work_available() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.reprocess_email(uuid, uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.reset_skipped_emails_for_sender_rule() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.trg_emails_broadcast() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.trg_event_sources_broadcast() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.trg_events_broadcast() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.trg_integrations_broadcast() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.unlock_expired_photo_locks() FROM PUBLIC;
