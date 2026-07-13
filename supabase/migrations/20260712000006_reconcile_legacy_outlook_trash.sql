-- Legacy Outlook ingestion marked every delta removal as Trash. A removal from
-- an included folder is a move/removal, not Deleted Items membership. Preserve
-- only rows whose provider labels explicitly prove Trash membership.
UPDATE public.emails
SET is_trash = false
WHERE email_provider = 'outlook'
  AND is_trash = true
  AND NOT ('TRASH' = ANY(provider_labels));
