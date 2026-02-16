-- Add importance classification to events
-- action_required: closures, schedule changes, deadlines (parent must act)
-- fyi: themed days, birthdays, informational (nice to know)
ALTER TABLE public.events
  ADD COLUMN importance text NOT NULL DEFAULT 'action_required'
  CHECK (importance IN ('action_required', 'fyi'));
