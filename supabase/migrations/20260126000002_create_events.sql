-- Migration: Create events table
-- Master deduplicated events (user's calendar)

CREATE TABLE public.events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,

    -- Event details (amalgamated from all sources)
    title text NOT NULL,
    start_datetime timestamptz,
    end_datetime timestamptz,
    all_day boolean DEFAULT false,
    location text,
    description text,
    
    -- Natural English attribution appended to calendar description
    -- e.g., "This event was automatically created from an email from WCSD on Jan 25th..."
    source_attribution text,

    -- Processing state (includes syncing and sync_failed for async job queue)
    status text NOT NULL DEFAULT 'pending_review'
        CHECK (status IN ('pending_review', 'approved', 'syncing', 'synced', 'sync_failed', 'cancelled', 'rejected')),

    -- External sync tracking
    google_calendar_event_id text,
    synced_at timestamptz,

    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL
);

ALTER TABLE public.events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage own events"
    ON public.events FOR ALL
    USING (auth.uid() = user_id);

-- Indexes
CREATE INDEX idx_events_user_status ON public.events(user_id, status);
CREATE INDEX idx_events_start_date ON public.events(user_id, start_datetime);
CREATE INDEX idx_events_user_id ON public.events(user_id);
