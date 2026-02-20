-- Create oauth_states table for persistent OAuth CSRF state storage
-- Replaces in-memory dict that was lost on server restart

CREATE TABLE IF NOT EXISTS public.oauth_states (
    state TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '10 minutes')
);

-- Index for cleanup of expired states
CREATE INDEX IF NOT EXISTS oauth_states_expires_at_idx
    ON public.oauth_states (expires_at);

-- Enable RLS
ALTER TABLE public.oauth_states ENABLE ROW LEVEL SECURITY;

-- Only service role can access this table (backend API uses service role for OAuth)
-- No user-facing RLS policies needed since users never query this table directly
CREATE POLICY "Service role full access to oauth_states"
    ON public.oauth_states
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
