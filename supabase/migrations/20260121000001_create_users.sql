-- Migration: Create users table
-- Extends Supabase auth.users with application-specific profile data

create table public.users (
    id uuid primary key references auth.users(id) on delete cascade,
    email text not null,
    display_name text,
    created_at timestamptz default now() not null,
    updated_at timestamptz default now() not null
);

alter table public.users enable row level security;

create policy "Users can view own profile"
    on public.users for select using (auth.uid() = id);

create policy "Users can update own profile"
    on public.users for update using (auth.uid() = id);
