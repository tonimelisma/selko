-- Migration: Create user_calendar_settings table
-- User preferences for calendar sync

CREATE TABLE public.user_calendar_settings (
    user_id uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,

    -- Target Google Calendar (null = primary calendar)
    target_calendar_id text,

    -- Default invitees to add to all events (comma-separated emails)
    default_invitees text,  -- e.g., "spouse@gmail.com,assistant@company.com"

    updated_at timestamptz DEFAULT now() NOT NULL
);

ALTER TABLE public.user_calendar_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage own calendar_settings"
    ON public.user_calendar_settings FOR ALL
    USING (auth.uid() = user_id);
