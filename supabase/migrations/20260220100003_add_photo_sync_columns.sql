-- Add photo sync tracking column to integrations table

ALTER TABLE public.integrations ADD COLUMN IF NOT EXISTS last_photo_sync_at TIMESTAMPTZ;
