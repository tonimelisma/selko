-- Migration: Create emails table
-- Stores synced Gmail messages with parsed label flags

create table public.emails (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.users(id) on delete cascade,
    integration_id uuid references public.integrations(id) on delete set null,

    -- Gmail identifiers
    gmail_id text not null,
    thread_id text,

    -- Headers
    subject text,
    from_email text,
    from_name text,
    to_emails text[],
    date_sent timestamptz,
    snippet text,

    -- Gmail labels (raw from API)
    gmail_label_ids text[] not null default '{}',

    -- Category flags (auto-computed by trigger)
    is_spam boolean default false,
    is_trash boolean default false,
    is_promotions boolean default false,
    is_social boolean default false,
    is_updates boolean default false,
    is_forums boolean default false,
    is_primary boolean default false,
    is_important boolean default false,
    is_starred boolean default false,
    is_unread boolean default true,

    -- Storage
    storage_path text,  -- Path in Supabase Storage for raw email
    has_attachments boolean default false,

    -- Dedup
    content_hash text,

    created_at timestamptz default now() not null,

    unique(user_id, gmail_id)
);

alter table public.emails enable row level security;

create policy "Users can manage own emails"
    on public.emails for all using (auth.uid() = user_id);

-- Indexes
create index idx_emails_user on public.emails(user_id);
create index idx_emails_gmail_id on public.emails(gmail_id);
create index idx_emails_date on public.emails(date_sent desc);

-- Trigger function to parse Gmail labels into boolean flags
create or replace function public.parse_gmail_labels()
returns trigger as $$
begin
    new.is_spam := 'SPAM' = any(new.gmail_label_ids);
    new.is_trash := 'TRASH' = any(new.gmail_label_ids);
    new.is_promotions := 'CATEGORY_PROMOTIONS' = any(new.gmail_label_ids);
    new.is_social := 'CATEGORY_SOCIAL' = any(new.gmail_label_ids);
    new.is_updates := 'CATEGORY_UPDATES' = any(new.gmail_label_ids);
    new.is_forums := 'CATEGORY_FORUMS' = any(new.gmail_label_ids);
    new.is_primary := 'CATEGORY_PERSONAL' = any(new.gmail_label_ids);
    new.is_important := 'IMPORTANT' = any(new.gmail_label_ids);
    new.is_starred := 'STARRED' = any(new.gmail_label_ids);
    new.is_unread := 'UNREAD' = any(new.gmail_label_ids);
    return new;
end;
$$ language plpgsql;

create trigger parse_gmail_labels_trigger
    before insert or update of gmail_label_ids on public.emails
    for each row execute function public.parse_gmail_labels();
