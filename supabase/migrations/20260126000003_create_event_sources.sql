-- Migration: Create event_sources table
-- Junction table tracking each email's contribution to events with undo support

CREATE TABLE public.event_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id uuid NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    email_id uuid NOT NULL REFERENCES public.emails(id) ON DELETE CASCADE,

    -- What type of info this email provided
    source_type text NOT NULL DEFAULT 'new_invitation'
        CHECK (source_type IN ('new_invitation', 'update', 'cancellation', 'reminder', 'unknown')),

    -- Raw extraction from this specific email (includes verbatim source_quote)
    extracted_data jsonb NOT NULL,
    -- Example extracted_data:
    -- {
    --   "title": "Birthday Party",
    --   "start_datetime": "2026-02-15T14:00:00Z",
    --   "location": "123 Main St",
    --   "description": "Celebrate with cake and games!",
    --   "source_quote": "You're invited to Sarah's birthday party on Feb 15th at 2pm..."
    -- }

    -- Snapshot of event BEFORE this merge (enables undo)
    event_snapshot_before jsonb,

    -- Undo tracking
    is_undone boolean DEFAULT false,

    created_at timestamptz DEFAULT now() NOT NULL,

    UNIQUE(event_id, email_id)
);

ALTER TABLE public.event_sources ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage own event_sources"
    ON public.event_sources FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.events 
            WHERE events.id = event_sources.event_id 
            AND events.user_id = auth.uid()
        )
    );

-- Indexes
CREATE INDEX idx_event_sources_event ON public.event_sources(event_id);
CREATE INDEX idx_event_sources_email ON public.event_sources(email_id);
