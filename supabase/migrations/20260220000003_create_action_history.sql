-- Action history for undo/redo support
-- Records user actions that can be reversed (approve, reject, edit, etc.)

CREATE TABLE public.action_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    action_type text NOT NULL,
    entity_type text NOT NULL,
    entity_id uuid NOT NULL,
    previous_state jsonb,
    new_state jsonb,
    external_resource_id text,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.action_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage own action history"
    ON public.action_history
    FOR ALL
    USING (auth.uid() = user_id);

CREATE INDEX action_history_user_created_idx
    ON public.action_history(user_id, created_at DESC);
