-- Migration: Create action_history table for undo/redo support
-- Records every user action with before/after state snapshots

CREATE TABLE IF NOT EXISTS public.action_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL CHECK (action_type IN ('create', 'update', 'delete')),
    entity_type TEXT NOT NULL CHECK (entity_type IN ('event', 'sender_rule')),
    entity_id UUID NOT NULL,
    previous_state JSONB,
    new_state JSONB,
    external_resource_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.action_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own action history"
    ON public.action_history FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own action history"
    ON public.action_history FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Service role full access to action_history"
    ON public.action_history FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

CREATE INDEX action_history_user_created_idx
    ON public.action_history (user_id, created_at DESC);

CREATE INDEX action_history_entity_idx
    ON public.action_history (entity_type, entity_id);
