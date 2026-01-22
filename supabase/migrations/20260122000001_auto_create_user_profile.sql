-- Migration: Auto-create user profile on signup
-- Creates a trigger that automatically populates public.users when a new user signs up

-- Trigger function to create public.users row on auth signup
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = ''
as $$
begin
  insert into public.users (id, email, display_name)
  values (new.id, new.email, split_part(new.email, '@', 1));
  return new;
end;
$$;

-- Trigger on auth.users insert
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Add INSERT policy for users table (needed for the trigger)
-- The trigger runs as security definer, but we also need a policy for direct inserts
create policy "Users can insert own profile"
    on public.users for insert with check (auth.uid() = id);
