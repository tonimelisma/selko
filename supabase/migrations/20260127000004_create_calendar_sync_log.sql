-- Migration: Create calendar_sync_log table
-- Tracks all calendar sync operations for audit trail and future drift detection

CREATE TABLE public.calendar_sync_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id uuid NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    google_calendar_event_id text NOT NULL,

    -- What we synced
    action text NOT NULL CHECK (action IN ('created', 'updated', 'deleted')),
    snapshot_synced jsonb NOT NULL,  -- What we sent to Google Calendar

    -- Timestamps
    synced_at timestamptz NOT NULL DEFAULT now()
);

-- RLS
ALTER TABLE public.calendar_sync_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own sync logs"
    ON public.calendar_sync_log FOR SELECT
    USING (user_id = auth.uid());

-- Indexes for efficient queries
CREATE INDEX calendar_sync_log_event_id_idx ON public.calendar_sync_log(event_id);
CREATE INDEX calendar_sync_log_user_id_idx ON public.calendar_sync_log(user_id);
CREATE INDEX calendar_sync_log_google_id_idx ON public.calendar_sync_log(google_calendar_event_id);
CREATE INDEX calendar_sync_log_synced_at_idx ON public.calendar_sync_log(synced_at DESC);
