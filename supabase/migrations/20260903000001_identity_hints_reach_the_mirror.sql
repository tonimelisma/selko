-- I3 of docs/specs/event-identity-reach.md: let identity hints name a mirrored
-- calendar entry, not only a Selko event.
--
-- event_id was NOT NULL, so only events Selko created could be found by
-- identity. An invite the user accepted elsewhere lives in calendar_entries and
-- has no event row, which is exactly the case that kept reappearing as New.

ALTER TABLE public.event_identity_hints
    ALTER COLUMN event_id DROP NOT NULL;

ALTER TABLE public.event_identity_hints
    ADD COLUMN IF NOT EXISTS calendar_entry_id uuid
        REFERENCES public.calendar_entries(id) ON DELETE CASCADE;

-- A hint names exactly one entity. Without this the table could hold a row that
-- points at both or neither, and the lookup would have to guess which it meant.
ALTER TABLE public.event_identity_hints
    ADD CONSTRAINT event_identity_hints_one_entity
    CHECK (num_nonnulls(event_id, calendar_entry_id) = 1);

-- The existing UNIQUE (event_id, kind, value_hash, recurrence_id) does not
-- constrain calendar-entry hints, because event_id is NULL for those and NULL
-- is distinct from NULL in a unique index. Give them their own.
CREATE UNIQUE INDEX IF NOT EXISTS event_identity_hints_calendar_entry_key
    ON public.event_identity_hints (calendar_entry_id, kind, value_hash, recurrence_id)
    WHERE calendar_entry_id IS NOT NULL;

COMMENT ON COLUMN public.event_identity_hints.calendar_entry_id IS
    'I3: the hint describes a mirrored calendar entry rather than a Selko event. Exactly one of event_id/calendar_entry_id is set.';
