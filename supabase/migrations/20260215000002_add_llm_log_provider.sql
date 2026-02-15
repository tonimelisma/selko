-- Add provider tracking to LLM call log for multi-provider support

ALTER TABLE llm_call_log ADD COLUMN IF NOT EXISTS provider TEXT;

COMMENT ON COLUMN llm_call_log.provider IS 'LLM provider name (gemini, moonshot, zai, qwen, deepseek, minimax)';
