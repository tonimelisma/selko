-- Migration: Make event_sources support non-email sources (Google Calendar, Google Photos)
-- Adds source_origin column, google_calendar_source_event_id, makes email_id nullable

-- Add source_origin column (all existing rows are email-sourced)
ALTER TABLE public.event_sources
    ADD COLUMN source_origin text NOT NULL DEFAULT 'email'
        CHECK (source_origin IN ('email', 'google_calendar', 'google_photos'));

-- Store Google Calendar event ID for calendar-sourced entries
ALTER TABLE public.event_sources
    ADD COLUMN google_calendar_source_event_id text;

-- Make email_id nullable (calendar sources have no email)
ALTER TABLE public.event_sources
    ALTER COLUMN email_id DROP NOT NULL;

-- Validate: email sources need email_id, calendar sources need gcal ID
ALTER TABLE public.event_sources
    ADD CONSTRAINT event_sources_origin_check CHECK (
        (source_origin = 'email' AND email_id IS NOT NULL)
        OR (source_origin = 'google_calendar' AND google_calendar_source_event_id IS NOT NULL)
        OR (source_origin = 'google_photos')
    );

-- Replace the old UNIQUE(event_id, email_id) with partial indexes
ALTER TABLE public.event_sources
    DROP CONSTRAINT IF EXISTS event_sources_event_id_email_id_key;

CREATE UNIQUE INDEX event_sources_event_email_unique
    ON public.event_sources(event_id, email_id)
    WHERE source_origin = 'email';

CREATE UNIQUE INDEX event_sources_event_gcal_unique
    ON public.event_sources(event_id, google_calendar_source_event_id)
    WHERE source_origin = 'google_calendar';
