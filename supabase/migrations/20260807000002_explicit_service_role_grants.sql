-- Hardening inc 8b: replace blanket GRANT ON ALL FUNCTIONS with explicit grants.
--
-- 20260801000001_polling_email_ingestion_v2.sql issued:
--   11× REVOKE ALL ... FROM PUBLIC (correct, per-function)
--   then one blanket:
--     GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO service_role;
-- The blanket is a snapshot (future functions not covered) and will silently
-- re-grant anything later intended to be restricted. Replace with eleven
-- explicit GRANTs so the grant set is auditable and so the integration test
-- can assert the expected set rather than merely that calls succeed.
--
-- Existing service_role grants from other migrations (e.g. integration recovery
-- RPCs 20260802000004/05 and 7a's withdrawn fix) already use explicit REVOKE/GRANT
-- per function and are not touched here.
--
-- This migration re-asserts the eleven grants explicitly. The earlier blanket
-- remains in the history but is now redundant; future migrations must use
-- explicit GRANT per function (see backend/tests/integration/test_integration_data_api_grants.py).

GRANT EXECUTE ON FUNCTION public.claim_due_email_sync(text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_due_email_reconciliation(text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.heartbeat_email_sync(uuid, text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.complete_email_sync(uuid, uuid, text, integer, boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.fail_email_sync(uuid, uuid, text, text, text, integer, integer, boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.upsert_discovered_email_items(uuid, uuid, jsonb, text, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_email_ingestion_item(text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.complete_email_ingestion_item(uuid, text, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.fail_email_ingestion_item(uuid, text, text, integer, integer, boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_email_attachment(text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.finish_email_attachment(uuid, text, text, text) TO service_role;

COMMENT ON SCHEMA public IS 'Explicit service_role grants required per hardening 8b; do not use GRANT ON ALL FUNCTIONS';
