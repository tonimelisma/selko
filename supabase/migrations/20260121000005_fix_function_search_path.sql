-- Migration: Fix function search_path security issue
-- Sets immutable search_path to prevent search_path injection attacks

create or replace function public.parse_gmail_labels()
returns trigger
security invoker
set search_path = ''
as $$
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
