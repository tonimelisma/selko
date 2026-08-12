-- Fix R4 events_status_check that dropped legacy sync statuses (syncing/synced/sync_failed)
-- The 20260813000004 migration truncated the check to 6 values, breaking complete_event_sync
-- (status='synced') and any existing rows. Restore legacy values plus new cancel_queued.
-- Correct set must match 20260710000001 (8 values) + cancel_queued = 9.
ALTER TABLE public.events DROP CONSTRAINT IF EXISTS events_status_check;
ALTER TABLE public.events ADD CONSTRAINT events_status_check
  CHECK (status IN (
    'pending_review',
    'pending_change',
    'approved',
    'rejected',
    'cancelled',
    'cancel_queued',
    'syncing',
    'synced',
    'sync_failed'
  ));
