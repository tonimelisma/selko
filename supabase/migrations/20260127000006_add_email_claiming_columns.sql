-- Migration: Add claiming columns to emails table for status-based worker processing
-- Part of the status-based worker pattern where data tables ARE the queue

ALTER TABLE public.emails
    ADD COLUMN locked_until timestamptz,
    ADD COLUMN locked_by text,
    ADD COLUMN attempts integer NOT NULL DEFAULT 0,
    ADD COLUMN max_attempts integer NOT NULL DEFAULT 3;

-- Partial index for efficient claiming of pending emails
-- This index only includes pending emails, making claims fast regardless of table size
CREATE INDEX idx_emails_pending_processing ON public.emails(processing_status, created_at)
    WHERE processing_status = 'pending';

COMMENT ON COLUMN public.emails.locked_until IS 'Prevents other workers from claiming until this time expires';
COMMENT ON COLUMN public.emails.locked_by IS 'Worker ID that claimed this email for processing';
COMMENT ON COLUMN public.emails.attempts IS 'Number of processing attempts made';
COMMENT ON COLUMN public.emails.max_attempts IS 'Maximum processing attempts before marking as failed';
