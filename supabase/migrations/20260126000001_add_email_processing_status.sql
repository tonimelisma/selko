-- Migration: Add processing status columns to emails table
-- Tracks email processing state for event extraction pipeline

ALTER TABLE public.emails
    ADD COLUMN processing_status text DEFAULT 'pending'
        CHECK (processing_status IN ('pending', 'processing', 'processed', 'failed', 'skipped')),
    ADD COLUMN processing_error text,
    ADD COLUMN processed_at timestamptz;

CREATE INDEX idx_emails_processing_status ON public.emails(processing_status);

-- Backfill existing emails with pending status
UPDATE public.emails SET processing_status = 'pending' WHERE processing_status IS NULL;
