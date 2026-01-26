-- Migration: Add updated_at triggers for events tables

-- Trigger for events table
CREATE TRIGGER set_events_updated_at
    BEFORE UPDATE ON public.events
    FOR EACH ROW
    EXECUTE FUNCTION public.set_updated_at();

-- Trigger for user_calendar_settings table
CREATE TRIGGER set_user_calendar_settings_updated_at
    BEFORE UPDATE ON public.user_calendar_settings
    FOR EACH ROW
    EXECUTE FUNCTION public.set_updated_at();
