-- Restrict Data API access to OAuth token columns on integrations.
--
-- 20260714000003 granted table-wide SELECT/INSERT/UPDATE/DELETE on
-- public.integrations to authenticated, which let any signed-in session read
-- access_token/refresh_token for its own rows via PostgREST column selection.
-- Token handling is a server-side (service_role) concern; frontends only list
-- integration metadata and delete rows to disconnect.
--
-- Replace the table-wide grant with column-level SELECT on the metadata
-- columns the frontends actually query, keep DELETE (disconnect), and drop
-- INSERT/UPDATE (rows are only written by the backend via service_role).

REVOKE SELECT, INSERT, UPDATE ON TABLE public.integrations FROM authenticated;

GRANT SELECT (
    id,
    user_id,
    provider,
    status,
    provider_email,
    scopes,
    last_sync_at,
    created_at,
    updated_at
) ON public.integrations TO authenticated;
