-- Migration: Create integrations table
-- Stores OAuth tokens and sync state for external providers (Gmail, Google Photos, etc.)

create type integration_provider as enum ('gmail', 'google_photos', 'google_calendar');
create type integration_status as enum ('active', 'expired', 'revoked', 'error');

create table public.integrations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.users(id) on delete cascade,
    provider integration_provider not null,
    status integration_status default 'active' not null,

    -- OAuth tokens
    access_token text not null,
    refresh_token text,
    token_expiry timestamptz,

    -- Provider info
    provider_email text,
    scopes text[] not null default '{}',

    -- Gmail sync state
    last_history_id text,
    last_sync_at timestamptz,

    created_at timestamptz default now() not null,
    updated_at timestamptz default now() not null,

    unique(user_id, provider)
);

alter table public.integrations enable row level security;

create policy "Users can manage own integrations"
    on public.integrations for all using (auth.uid() = user_id);
