-- Add indexes for common query patterns

-- Composite index for user's emails by date (most common query)
CREATE INDEX IF NOT EXISTS idx_emails_user_date
    ON public.emails(user_id, date_sent DESC);

-- Index for content deduplication
CREATE INDEX IF NOT EXISTS idx_emails_content_hash
    ON public.emails(user_id, content_hash)
    WHERE content_hash IS NOT NULL;

-- Index for integration status queries
CREATE INDEX IF NOT EXISTS idx_integrations_user_status
    ON public.integrations(user_id, status);

-- Index for attachment content deduplication
CREATE INDEX IF NOT EXISTS idx_attachments_content_hash
    ON public.attachments(user_id, content_hash)
    WHERE content_hash IS NOT NULL;
