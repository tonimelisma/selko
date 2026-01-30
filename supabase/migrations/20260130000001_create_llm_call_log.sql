-- Migration: Create llm_call_log table for comprehensive LLM call auditing
-- This enables tracking all LLM calls with prompts, responses, latency, and cost
-- NOTE: This migration was missing from PR #17 which merged the Python code

-- Create operation type enum for LLM calls
CREATE TYPE public.llm_operation_type AS ENUM (
    'extract_events',      -- extract_calendar_events()
    'compare_events',      -- compare_events() for deduplication
    'merge_events'         -- merge_event_data() for updates
);

-- Create llm_call_log table
CREATE TABLE public.llm_call_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,

    -- Request metadata
    operation_type llm_operation_type NOT NULL,
    model TEXT NOT NULL,                          -- e.g., 'gemini-3-flash-preview'
    email_id UUID REFERENCES public.emails(id) ON DELETE SET NULL,  -- optional: linked email

    -- Input/Output storage
    prompt_text TEXT NOT NULL,                    -- Full prompt sent to LLM
    response_text TEXT,                           -- Full response from LLM (null on error)

    -- Token usage (from API response if available)
    prompt_tokens INTEGER,                        -- Input tokens
    completion_tokens INTEGER,                    -- Output tokens
    total_tokens INTEGER,                         -- Total tokens

    -- Timing
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,                     -- null if in-progress or failed
    latency_ms INTEGER,                           -- Duration in milliseconds

    -- Status
    success BOOLEAN NOT NULL DEFAULT true,
    error_message TEXT,                           -- Error details if failed
    error_type TEXT,                              -- Error classification (rate_limit, api_error, etc.)

    -- Cost tracking (for future billing)
    estimated_cost_usd NUMERIC(10, 6),            -- Estimated cost based on token pricing

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Enable RLS
ALTER TABLE public.llm_call_log ENABLE ROW LEVEL SECURITY;

-- Users can view their own LLM call history
CREATE POLICY "Users can view own llm calls"
    ON public.llm_call_log
    FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

-- Service role can manage all logs (needed for writes from backend)
CREATE POLICY "Service role can manage llm call logs"
    ON public.llm_call_log
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Indexes for common queries
CREATE INDEX idx_llm_call_log_user_date ON public.llm_call_log(user_id, started_at DESC);
CREATE INDEX idx_llm_call_log_email ON public.llm_call_log(email_id) WHERE email_id IS NOT NULL;
CREATE INDEX idx_llm_call_log_operation ON public.llm_call_log(operation_type);
CREATE INDEX idx_llm_call_log_success ON public.llm_call_log(success) WHERE success = false;

-- Function to get user's LLM usage summary for a date range
CREATE OR REPLACE FUNCTION get_llm_usage_summary(
    p_user_id UUID,
    p_start_date DATE DEFAULT CURRENT_DATE,
    p_end_date DATE DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    total_calls INTEGER,
    successful_calls INTEGER,
    failed_calls INTEGER,
    total_tokens BIGINT,
    total_prompt_tokens BIGINT,
    total_completion_tokens BIGINT,
    total_latency_ms BIGINT,
    avg_latency_ms INTEGER,
    estimated_cost_usd NUMERIC(10, 6),
    calls_by_operation JSONB
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    SELECT
        COUNT(*)::INTEGER AS total_calls,
        COUNT(*) FILTER (WHERE l.log_success = true)::INTEGER AS successful_calls,
        COUNT(*) FILTER (WHERE l.log_success = false)::INTEGER AS failed_calls,
        COALESCE(SUM(l.log_total_tokens), 0)::BIGINT AS total_tokens,
        COALESCE(SUM(l.log_prompt_tokens), 0)::BIGINT AS total_prompt_tokens,
        COALESCE(SUM(l.log_completion_tokens), 0)::BIGINT AS total_completion_tokens,
        COALESCE(SUM(l.log_latency_ms), 0)::BIGINT AS total_latency_ms,
        COALESCE(AVG(l.log_latency_ms)::INTEGER, 0) AS avg_latency_ms,
        COALESCE(SUM(l.log_estimated_cost_usd), 0)::NUMERIC(10, 6) AS estimated_cost_usd,
        COALESCE(
            jsonb_object_agg(
                l.log_operation_type::TEXT,
                l.op_count
            ),
            '{}'::JSONB
        ) AS calls_by_operation
    FROM (
        SELECT
            success AS log_success,
            total_tokens AS log_total_tokens,
            prompt_tokens AS log_prompt_tokens,
            completion_tokens AS log_completion_tokens,
            latency_ms AS log_latency_ms,
            estimated_cost_usd AS log_estimated_cost_usd,
            operation_type AS log_operation_type,
            COUNT(*) OVER (PARTITION BY operation_type) AS op_count
        FROM llm_call_log
        WHERE user_id = p_user_id
        AND started_at >= p_start_date
        AND started_at < p_end_date + INTERVAL '1 day'
    ) l;
END;
$$;

GRANT EXECUTE ON FUNCTION get_llm_usage_summary(UUID, DATE, DATE) TO authenticated;

-- Comment on table
COMMENT ON TABLE public.llm_call_log IS 'Audit log of all LLM API calls with prompts, responses, and metrics';
COMMENT ON COLUMN public.llm_call_log.prompt_text IS 'Full prompt sent to the LLM (may be large for multimodal calls)';
COMMENT ON COLUMN public.llm_call_log.response_text IS 'Full response text from LLM (null on error)';
COMMENT ON COLUMN public.llm_call_log.latency_ms IS 'API call duration in milliseconds';
COMMENT ON COLUMN public.llm_call_log.estimated_cost_usd IS 'Estimated cost based on current Gemini pricing';
