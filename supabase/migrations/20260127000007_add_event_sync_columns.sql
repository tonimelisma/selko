-- Migration: Add sync tracking columns to events table for status-based worker processing
-- Part of the status-based worker pattern where data tables ARE the queue

ALTER TABLE public.events
    ADD COLUMN locked_until timestamptz,
    ADD COLUMN locked_by text,
    ADD COLUMN sync_attempts integer NOT NULL DEFAULT 0,
    ADD COLUMN max_sync_attempts integer NOT NULL DEFAULT 3,
    ADD COLUMN sync_error text;

-- Partial index for efficient claiming of approved events awaiting sync
-- This index only includes approved events, making claims fast regardless of table size
CREATE INDEX idx_events_approved ON public.events(status, updated_at)
    WHERE status = 'approved';

COMMENT ON COLUMN public.events.locked_until IS 'Prevents other workers from claiming until this time expires';
COMMENT ON COLUMN public.events.locked_by IS 'Worker ID that claimed this event for syncing';
COMMENT ON COLUMN public.events.sync_attempts IS 'Number of sync attempts made';
COMMENT ON COLUMN public.events.max_sync_attempts IS 'Maximum sync attempts before marking as sync_failed';
COMMENT ON COLUMN public.events.sync_error IS 'Last sync error message if sync failed';
