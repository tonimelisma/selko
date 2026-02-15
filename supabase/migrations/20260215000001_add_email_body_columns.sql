-- Add full email body columns for enhanced LLM processing
-- body_text: plain text email body (full content, not just snippet)
-- body_html: HTML email body (used for linked image extraction)

ALTER TABLE emails ADD COLUMN IF NOT EXISTS body_text TEXT;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS body_html TEXT;

COMMENT ON COLUMN emails.body_text IS 'Full plain-text email body (from MIME text/plain part)';
COMMENT ON COLUMN emails.body_html IS 'HTML email body (from MIME text/html part, used for linked image extraction)';
