-- Migration: Global all-day materialization preference
-- Controls how date-only (all_day=true) extractions events are stored on the
-- events row. Source truth remains all_day in event_sources.extracted_data.

ALTER TABLE public.user_calendar_settings
    ADD COLUMN all_day_display_mode text NOT NULL DEFAULT 'all_day'
        CHECK (all_day_display_mode IN (
            'all_day',
            'day_9_to_5',
            'morning_8_to_9',
            'custom'
        )),
    ADD COLUMN all_day_custom_start time,
    ADD COLUMN all_day_custom_end time;

ALTER TABLE public.user_calendar_settings
    ADD CONSTRAINT user_calendar_settings_all_day_custom_times_check
    CHECK (
        (
            all_day_display_mode = 'custom'
            AND all_day_custom_start IS NOT NULL
            AND all_day_custom_end IS NOT NULL
            AND all_day_custom_end > all_day_custom_start
        )
        OR (
            all_day_display_mode <> 'custom'
        )
    );
