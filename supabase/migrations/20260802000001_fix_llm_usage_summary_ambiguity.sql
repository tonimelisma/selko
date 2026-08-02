-- Fix `column reference "total_tokens" is ambiguous` in get_llm_usage_summary.
--
-- The RETURNS TABLE signature declares out-parameters named total_tokens,
-- total_prompt_tokens, total_completion_tokens, total_latency_ms and
-- estimated_cost_usd. Those become PL/pgSQL variables that shadow the
-- identically named llm_call_log columns referenced in the inner subquery, so
-- the function raised at execution time and get_user_usage_summary() has been
-- swallowing the error and returning {} since 20260130000001 shipped.
--
-- Qualifying every column reference with the source table alias resolves the
-- shadowing without changing the function's signature or result shape.

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
            c.success AS log_success,
            c.total_tokens AS log_total_tokens,
            c.prompt_tokens AS log_prompt_tokens,
            c.completion_tokens AS log_completion_tokens,
            c.latency_ms AS log_latency_ms,
            c.estimated_cost_usd AS log_estimated_cost_usd,
            c.operation_type AS log_operation_type,
            COUNT(*) OVER (PARTITION BY c.operation_type) AS op_count
        FROM llm_call_log c
        WHERE c.user_id = p_user_id
        AND c.started_at >= p_start_date
        AND c.started_at < p_end_date + INTERVAL '1 day'
    ) l;
END;
$$;

GRANT EXECUTE ON FUNCTION get_llm_usage_summary(UUID, DATE, DATE) TO authenticated;
