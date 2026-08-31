-- Make the calendar-entry hint index usable by ON CONFLICT.
--
-- 20260903000001 created it partial:
--
--   CREATE UNIQUE INDEX ... (calendar_entry_id, kind, value_hash, recurrence_id)
--   WHERE calendar_entry_id IS NOT NULL;
--
-- PostgreSQL cannot infer a partial unique index from an ON CONFLICT target
-- unless the statement repeats the index predicate, and PostgREST offers no way
-- to express that. Every mirrored entry therefore failed to index with
-- SQLSTATE 42P10, "there is no unique or exclusion constraint matching the ON
-- CONFLICT specification" -- production mirrored 1595 calendar entries carrying
-- 1595 iCalUIDs and wrote zero hints.
--
-- The predicate was never needed. NULL is distinct from NULL in a unique index,
-- so a plain index constrains calendar-entry hints exactly as intended while
-- leaving event hints -- where calendar_entry_id is NULL -- unconstrained. The
-- property the predicate was added for comes free from NULL semantics, and
-- dropping it restores inference.

DROP INDEX IF EXISTS public.event_identity_hints_calendar_entry_key;

CREATE UNIQUE INDEX IF NOT EXISTS event_identity_hints_calendar_entry_key
    ON public.event_identity_hints (calendar_entry_id, kind, value_hash, recurrence_id);

COMMENT ON INDEX public.event_identity_hints_calendar_entry_key IS
    'Not partial: ON CONFLICT cannot infer a partial index. NULL calendar_entry_id rows (event hints) stay unconstrained because NULL is distinct from NULL.';
