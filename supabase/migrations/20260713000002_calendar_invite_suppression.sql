-- Migration: Calendar invitation emails never become Selko suggestions
--
-- Meeting requests/updates/RSVPs/cancellations from Outlook (eventMessage
-- subtypes) or Gmail (RFC 5545 REQUEST/REPLY/CANCEL/... .ics attachments) are
-- already handled by the user's email client and calendar. Selko skips them
-- entirely rather than mirroring them as review-list suggestions.

ALTER TABLE public.emails
    ADD COLUMN IF NOT EXISTS is_calendar_invite boolean NOT NULL DEFAULT false;

ALTER TABLE public.emails
    DROP CONSTRAINT IF EXISTS emails_processing_outcome_check;

ALTER TABLE public.emails
    ADD CONSTRAINT emails_processing_outcome_check
    CHECK (processing_outcome IS NULL OR processing_outcome IN (
        'no_event',
        'event_matched',
        'event_created',
        'event_updated',
        'event_created_and_updated',
        'event_cancelled',
        'calendar_invite'
    ));
