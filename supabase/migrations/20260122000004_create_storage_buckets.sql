-- Migration: Create storage bucket for email attachments
-- Stores email attachments with user-scoped RLS policies

-- Create the attachments bucket (private, not public)
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'attachments',
    'attachments',
    false,  -- private bucket
    52428800,  -- 50 MB limit (50 * 1024 * 1024)
    array['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml',
          'application/pdf',
          'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          'application/vnd.ms-powerpoint', 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
          'text/plain', 'text/csv', 'text/html',
          'application/zip', 'application/x-zip-compressed',
          'application/octet-stream']
);

-- RLS Policy: Users can upload to their own folder (user_id/*)
-- Uses auth.uid() to get current user from JWT
create policy "Users can upload own attachments"
on storage.objects for insert
to authenticated
with check (
    bucket_id = 'attachments' and
    (storage.foldername(name))[1] = (select auth.uid()::text)
);

-- RLS Policy: Users can read their own attachments
create policy "Users can read own attachments"
on storage.objects for select
to authenticated
using (
    bucket_id = 'attachments' and
    (storage.foldername(name))[1] = (select auth.uid()::text)
);

-- RLS Policy: Users can update their own attachments
create policy "Users can update own attachments"
on storage.objects for update
to authenticated
using (
    bucket_id = 'attachments' and
    (storage.foldername(name))[1] = (select auth.uid()::text)
)
with check (
    bucket_id = 'attachments' and
    (storage.foldername(name))[1] = (select auth.uid()::text)
);

-- RLS Policy: Users can delete their own attachments
create policy "Users can delete own attachments"
on storage.objects for delete
to authenticated
using (
    bucket_id = 'attachments' and
    (storage.foldername(name))[1] = (select auth.uid()::text)
);

-- Add index on content_hash for deduplication lookups
create index if not exists idx_attachments_content_hash on public.attachments(user_id, content_hash);
