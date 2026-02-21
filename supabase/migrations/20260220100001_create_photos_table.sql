-- Create photos table for Google Photos integration

CREATE TABLE IF NOT EXISTS public.photos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    google_photo_id TEXT NOT NULL,
    filename TEXT,
    description TEXT,
    mime_type TEXT,
    date_taken TIMESTAMPTZ,
    width INTEGER,
    height INTEGER,
    location_latitude NUMERIC,
    location_longitude NUMERIC,
    location_display_name TEXT,
    storage_path TEXT,
    content_hash TEXT,
    processing_status TEXT NOT NULL DEFAULT 'pending' CHECK (processing_status IN ('pending', 'processing', 'processed', 'failed', 'skipped')),
    processing_error TEXT,
    processed_at TIMESTAMPTZ,
    locked_until TIMESTAMPTZ,
    locked_by TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    next_retry_at TIMESTAMPTZ,
    dead_letter_reason TEXT,
    dead_letter_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, google_photo_id)
);

ALTER TABLE public.photos ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own photos" ON public.photos FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users can insert own photos" ON public.photos FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users can update own photos" ON public.photos FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "Users can delete own photos" ON public.photos FOR DELETE USING (auth.uid() = user_id);

CREATE POLICY "Service role full access to photos" ON public.photos FOR ALL
    USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');

CREATE INDEX photos_pending_idx ON public.photos (processing_status, created_at)
    WHERE processing_status = 'pending';

CREATE INDEX photos_user_idx ON public.photos (user_id, created_at DESC);
