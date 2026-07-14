-- Explicitly expose application tables through the Data API.
--
-- Supabase no longer grants SELECT/INSERT/UPDATE/DELETE on new public tables
-- by default. RLS remains the row-level authorization layer; these grants only
-- make the operations covered by the existing policies reachable via
-- PostgREST. Keep anonymous access disabled and grant each authenticated table
-- only the operations its policies support.

REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE
    public.action_history,
    public.attachments,
    public.calendar_sync_log,
    public.email_folders,
    public.emails,
    public.event_sources,
    public.events,
    public.global_limits,
    public.integrations,
    public.llm_call_log,
    public.oauth_states,
    public.photos,
    public.scheduled_tasks,
    public.sender_rules,
    public.usage_quotas,
    public.user_calendar_settings,
    public.users
FROM anon, authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    public.action_history,
    public.attachments,
    public.calendar_sync_log,
    public.email_folders,
    public.emails,
    public.event_sources,
    public.events,
    public.global_limits,
    public.integrations,
    public.llm_call_log,
    public.oauth_states,
    public.photos,
    public.scheduled_tasks,
    public.sender_rules,
    public.usage_quotas,
    public.user_calendar_settings,
    public.users
TO service_role;

GRANT SELECT, INSERT ON TABLE public.action_history TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.attachments TO authenticated;
GRANT SELECT, INSERT ON TABLE public.calendar_sync_log TO authenticated;
GRANT SELECT ON TABLE public.email_folders TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.emails TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.event_sources TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.events TO authenticated;
GRANT SELECT ON TABLE public.global_limits TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.integrations TO authenticated;
GRANT SELECT ON TABLE public.llm_call_log TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.photos TO authenticated;
GRANT SELECT ON TABLE public.scheduled_tasks TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.sender_rules TO authenticated;
GRANT SELECT ON TABLE public.usage_quotas TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.user_calendar_settings TO authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.users TO authenticated;
