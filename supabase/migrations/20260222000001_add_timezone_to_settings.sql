-- Migration: Add timezone column to user_calendar_settings
-- Stores user's IANA timezone (e.g., "America/New_York") for correct
-- datetime localization in event extraction and Google Calendar sync.

ALTER TABLE public.user_calendar_settings
    ADD COLUMN timezone text DEFAULT 'America/New_York' NOT NULL;
