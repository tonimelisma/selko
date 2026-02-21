-- Migration: Add explicit deny policies for UPDATE/DELETE on action_history
-- and composite index for action_type filtering.
-- The table is append-only; these policies make that intent explicit in RLS.

CREATE POLICY "Deny updates to action_history"
    ON public.action_history FOR UPDATE
    USING (false);

CREATE POLICY "Deny deletes from action_history"
    ON public.action_history FOR DELETE
    USING (false);

CREATE INDEX action_history_user_action_type_idx
    ON public.action_history (user_id, action_type, created_at DESC);
