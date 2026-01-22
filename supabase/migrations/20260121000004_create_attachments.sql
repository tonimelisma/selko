-- Migration: Create attachments table
-- Stores email attachment metadata with references to Supabase Storage

create table public.attachments (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null references public.users(id) on delete cascade,
    email_id uuid not null references public.emails(id) on delete cascade,

    gmail_attachment_id text,
    filename text not null,
    mime_type text,
    size_bytes bigint,

    storage_path text,  -- Path in Supabase Storage
    content_hash text,

    created_at timestamptz default now() not null
);

alter table public.attachments enable row level security;

create policy "Users can manage own attachments"
    on public.attachments for all using (auth.uid() = user_id);

create index idx_attachments_email on public.attachments(email_id);
