-- Migration: Create usage_quotas and global_limits tables for rate limiting
-- This enables per-user daily tracking of LLM, email sync, and calendar sync usage

-- Create global_limits table (admin-configurable defaults)
CREATE TABLE public.global_limits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    limit_type TEXT NOT NULL UNIQUE,  -- 'llm_calls_daily', 'email_syncs_daily', etc.
    default_limit INTEGER NOT NULL,
    max_allowed INTEGER NOT NULL,      -- hard cap even for paid users
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Enable RLS on global_limits (read-only for authenticated users)
ALTER TABLE public.global_limits ENABLE ROW LEVEL SECURITY;

-- Anyone can read global limits
CREATE POLICY "Authenticated users can view global limits"
    ON public.global_limits
    FOR SELECT
    TO authenticated
    USING (true);

-- Only service role can modify global limits
CREATE POLICY "Service role can manage global limits"
    ON public.global_limits
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Seed default limits
INSERT INTO public.global_limits (limit_type, default_limit, max_allowed) VALUES
    ('llm_calls_daily', 100, 1000),
    ('email_syncs_daily', 50, 500),
    ('calendar_syncs_daily', 100, 1000);

-- Create usage_quotas table
CREATE TABLE public.usage_quotas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    date DATE NOT NULL DEFAULT CURRENT_DATE,

    -- LLM Usage (tracked per day)
    llm_calls_count INTEGER NOT NULL DEFAULT 0,
    llm_calls_limit INTEGER NOT NULL DEFAULT 100,

    -- Email Sync Usage (tracked per day)
    email_syncs_count INTEGER NOT NULL DEFAULT 0,
    email_syncs_limit INTEGER NOT NULL DEFAULT 50,

    -- Calendar Syncs (tracked per day)
    calendar_syncs_count INTEGER NOT NULL DEFAULT 0,
    calendar_syncs_limit INTEGER NOT NULL DEFAULT 100,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One row per user per day
    UNIQUE(user_id, date)
);

-- Enable RLS
ALTER TABLE public.usage_quotas ENABLE ROW LEVEL SECURITY;

-- Users can view their own usage
CREATE POLICY "Users can view own usage"
    ON public.usage_quotas
    FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

-- Service role can manage all quotas (needed for atomic increment)
CREATE POLICY "Service role can manage quotas"
    ON public.usage_quotas
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Index for fast daily lookups
CREATE INDEX idx_usage_quotas_user_date ON public.usage_quotas(user_id, date);

-- Add updated_at trigger
CREATE TRIGGER set_usage_quotas_updated_at
    BEFORE UPDATE ON public.usage_quotas
    FOR EACH ROW
    EXECUTE FUNCTION public.set_updated_at();

CREATE TRIGGER set_global_limits_updated_at
    BEFORE UPDATE ON public.global_limits
    FOR EACH ROW
    EXECUTE FUNCTION public.set_updated_at();

-- Create function for atomic check-and-increment
-- Returns: allowed (bool), current_count, limit, remaining
CREATE OR REPLACE FUNCTION check_and_increment_quota(
    p_user_id UUID,
    p_quota_type TEXT,
    p_increment INTEGER DEFAULT 1
)
RETURNS TABLE (
    allowed BOOLEAN,
    current_count INTEGER,
    quota_limit INTEGER,
    remaining INTEGER
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_count_col TEXT;
    v_limit_col TEXT;
    v_default_limit INTEGER;
    v_current_count INTEGER;
    v_limit INTEGER;
    v_new_count INTEGER;
BEGIN
    -- Map quota type to column names
    CASE p_quota_type
        WHEN 'llm_calls' THEN
            v_count_col := 'llm_calls_count';
            v_limit_col := 'llm_calls_limit';
        WHEN 'email_syncs' THEN
            v_count_col := 'email_syncs_count';
            v_limit_col := 'email_syncs_limit';
        WHEN 'calendar_syncs' THEN
            v_count_col := 'calendar_syncs_count';
            v_limit_col := 'calendar_syncs_limit';
        ELSE
            RAISE EXCEPTION 'Invalid quota type: %', p_quota_type;
    END CASE;

    -- Get default limit from global_limits
    SELECT default_limit INTO v_default_limit
    FROM global_limits
    WHERE limit_type = p_quota_type || '_daily' AND is_active = true;

    IF v_default_limit IS NULL THEN
        v_default_limit := 100;  -- Fallback default
    END IF;

    -- Try to insert or get existing row, then conditionally update
    -- Using advisory lock to prevent race conditions
    PERFORM pg_advisory_xact_lock(hashtext(p_user_id::text || CURRENT_DATE::text));

    -- Get or create today's quota row
    INSERT INTO usage_quotas (user_id, date, llm_calls_limit, email_syncs_limit, calendar_syncs_limit)
    VALUES (
        p_user_id,
        CURRENT_DATE,
        (SELECT COALESCE(default_limit, 100) FROM global_limits WHERE limit_type = 'llm_calls_daily'),
        (SELECT COALESCE(default_limit, 50) FROM global_limits WHERE limit_type = 'email_syncs_daily'),
        (SELECT COALESCE(default_limit, 100) FROM global_limits WHERE limit_type = 'calendar_syncs_daily')
    )
    ON CONFLICT (user_id, date) DO NOTHING;

    -- Now read current values using dynamic SQL
    EXECUTE format(
        'SELECT %I, %I FROM usage_quotas WHERE user_id = $1 AND date = CURRENT_DATE',
        v_count_col, v_limit_col
    ) INTO v_current_count, v_limit USING p_user_id;

    -- Check if increment would exceed limit
    IF v_current_count + p_increment > v_limit THEN
        -- Quota exceeded, don't increment
        RETURN QUERY SELECT
            false AS allowed,
            v_current_count AS current_count,
            v_limit AS quota_limit,
            GREATEST(0, v_limit - v_current_count) AS remaining;
        RETURN;
    END IF;

    -- Increment the count
    v_new_count := v_current_count + p_increment;
    EXECUTE format(
        'UPDATE usage_quotas SET %I = $1, updated_at = NOW() WHERE user_id = $2 AND date = CURRENT_DATE',
        v_count_col
    ) USING v_new_count, p_user_id;

    RETURN QUERY SELECT
        true AS allowed,
        v_new_count AS current_count,
        v_limit AS quota_limit,
        GREATEST(0, v_limit - v_new_count) AS remaining;
END;
$$;

-- Grant execute to authenticated users (function uses SECURITY DEFINER)
GRANT EXECUTE ON FUNCTION check_and_increment_quota(UUID, TEXT, INTEGER) TO authenticated;

-- Create function to get current usage without incrementing
CREATE OR REPLACE FUNCTION get_user_quota_usage(
    p_user_id UUID,
    p_date DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    llm_calls_count INTEGER,
    llm_calls_limit INTEGER,
    llm_calls_remaining INTEGER,
    email_syncs_count INTEGER,
    email_syncs_limit INTEGER,
    email_syncs_remaining INTEGER,
    calendar_syncs_count INTEGER,
    calendar_syncs_limit INTEGER,
    calendar_syncs_remaining INTEGER
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    SELECT
        COALESCE(q.llm_calls_count, 0) AS llm_calls_count,
        COALESCE(q.llm_calls_limit, gl_llm.default_limit, 100) AS llm_calls_limit,
        GREATEST(0, COALESCE(q.llm_calls_limit, gl_llm.default_limit, 100) - COALESCE(q.llm_calls_count, 0)) AS llm_calls_remaining,
        COALESCE(q.email_syncs_count, 0) AS email_syncs_count,
        COALESCE(q.email_syncs_limit, gl_email.default_limit, 50) AS email_syncs_limit,
        GREATEST(0, COALESCE(q.email_syncs_limit, gl_email.default_limit, 50) - COALESCE(q.email_syncs_count, 0)) AS email_syncs_remaining,
        COALESCE(q.calendar_syncs_count, 0) AS calendar_syncs_count,
        COALESCE(q.calendar_syncs_limit, gl_cal.default_limit, 100) AS calendar_syncs_limit,
        GREATEST(0, COALESCE(q.calendar_syncs_limit, gl_cal.default_limit, 100) - COALESCE(q.calendar_syncs_count, 0)) AS calendar_syncs_remaining
    FROM (SELECT 1) AS dummy
    LEFT JOIN usage_quotas q ON q.user_id = p_user_id AND q.date = p_date
    LEFT JOIN global_limits gl_llm ON gl_llm.limit_type = 'llm_calls_daily'
    LEFT JOIN global_limits gl_email ON gl_email.limit_type = 'email_syncs_daily'
    LEFT JOIN global_limits gl_cal ON gl_cal.limit_type = 'calendar_syncs_daily';
END;
$$;

GRANT EXECUTE ON FUNCTION get_user_quota_usage(UUID, DATE) TO authenticated;
