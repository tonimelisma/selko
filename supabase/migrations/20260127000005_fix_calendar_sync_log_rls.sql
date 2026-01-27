-- Fix: Add INSERT policy for calendar_sync_log table
-- The sync function uses authenticated client to insert logs

CREATE POLICY "Users can insert own sync logs"
    ON public.calendar_sync_log FOR INSERT
    WITH CHECK (user_id = auth.uid());
