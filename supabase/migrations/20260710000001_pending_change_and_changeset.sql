-- Two-lane review: pending_change status + structured change_set on event_sources

-- Expand events.status to include pending_change
ALTER TABLE public.events
    DROP CONSTRAINT IF EXISTS events_status_check;

ALTER TABLE public.events
    ADD CONSTRAINT events_status_check
    CHECK (status IN (
        'pending_review',
        'pending_change',
        'approved',
        'syncing',
        'synced',
        'sync_failed',
        'cancelled',
        'rejected'
    ));

-- Field-level diff for Changes lane + History
ALTER TABLE public.event_sources
    ADD COLUMN IF NOT EXISTS change_set jsonb;

-- LLM propose_event_update operation
ALTER TYPE public.llm_operation_type ADD VALUE IF NOT EXISTS 'propose_event_update';
