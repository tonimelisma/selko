-- Fixture rows for the image's import check (scripts/image-import-check.sh).
-- Synthetic: example.test addresses, placeholder tokens, the public password
-- "fixture-password" (bcrypt, GoTrue's $2a$10$ form, so it signs in unchanged).
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE auth.users (
  id uuid PRIMARY KEY,
  email text,
  encrypted_password text,
  email_confirmed_at timestamptz,
  created_at timestamptz,
  updated_at timestamptz,
  last_sign_in_at timestamptz,
  deleted_at timestamptz
);
INSERT INTO auth.users VALUES
  ('11111111-1111-4111-8111-111111111111', 'Fixture@Example.test',
   '$2a$10$M4IFWZx0OZKpMkq9M5tL2epMLOwxtf0/zeTONaa6dh3NjiFMkKCSC',
   '2026-01-02 03:04:05.123456+00', '2026-01-02 03:04:05.123456+00', '2026-06-01 10:00:00+00', NULL, NULL),
  -- deleted: never carried
  ('22222222-2222-4222-8222-222222222222', 'gone@example.test', '$2a$10$M4IFWZx0OZKpMkq9M5tL2epMLOwxtf0/zeTONaa6dh3NjiFMkKCSC',
   NULL, '2026-01-02 00:00:00+00', NULL, NULL, '2026-02-01 00:00:00+00');

INSERT INTO public.users (id, email, display_name, created_at, updated_at) VALUES
  ('11111111-1111-4111-8111-111111111111', 'fixture@example.test', 'Fixture Person',
   '2026-01-02 03:04:05.123456', '2026-06-01 10:00:00');

INSERT INTO public.user_calendar_settings (user_id, target_calendar_id, updated_at, timezone, all_day_display_mode) VALUES
  ('11111111-1111-4111-8111-111111111111', 'primary', '2026-06-01 10:00:00', 'Europe/Helsinki', 'all_day');

INSERT INTO public.integrations (id, user_id, provider, status, access_token, refresh_token, token_expiry,
  provider_email, scopes, created_at, updated_at) VALUES
  ('33333333-3333-4333-8333-333333333333', '11111111-1111-4111-8111-111111111111', 'gmail', 'active',
   'fixture-not-a-token', 'fixture-not-a-token', '2026-06-01 11:00:00', 'fixture@example.test',
   ARRAY['https://www.googleapis.com/auth/gmail.readonly'], '2026-01-02 03:10:00', '2026-06-01 10:00:00');

INSERT INTO public.emails (id, user_id, integration_id, provider_message_id, thread_id, subject, from_email, from_name,
  to_emails, date_sent, snippet, provider_labels, has_attachments, created_at, processing_status, processed_at,
  attempts, max_attempts, body_text, email_provider, processing_outcome, processing_result, lock_generation) VALUES
  ('44444444-4444-4444-8444-444444444441', '11111111-1111-4111-8111-111111111111', '33333333-3333-4333-8333-333333333333',
   'fixture-msg-1', 'fixture-thread-1', 'School play on Friday', 'office@school.example.test', 'School "Office"',
   ARRAY['fixture@example.test'], '2026-05-30 08:15:00.5', 'The play starts at 6pm — tickets attached',
   ARRAY['INBOX', 'CATEGORY_UPDATES'], true, '2026-05-30 08:16:00', 'processed', '2026-05-30 08:17:00',
   1, 3, E'Hello,\nThe play starts at 6pm.\tBring the ticket.\n', 'gmail', 'event_created',
   '{"events": [{"title": "School play", "confidence": 0.93}], "note": "ünïcode ✓"}', 1),
  ('44444444-4444-4444-8444-444444444442', '11111111-1111-4111-8111-111111111111', '33333333-3333-4333-8333-333333333333',
   'fixture-msg-2', 'fixture-thread-2', 'Dentist reminder', 'reception@dentist.example.test', NULL,
   ARRAY['fixture@example.test'], '2026-05-31 09:00:00', 'Your appointment', ARRAY['INBOX'], false,
   '2026-05-31 09:01:00', 'processed', '2026-05-31 09:02:00', 1, 3, 'Appointment on June 10 at 9:30.', 'gmail',
   'event_created', '{}', 1);

INSERT INTO public.attachments (id, user_id, email_id, provider_attachment_id, filename, mime_type, size_bytes,
  storage_path, created_at, ingestion_status, attempts, max_attempts) VALUES
  ('55555555-5555-4555-8555-555555555555', '11111111-1111-4111-8111-111111111111', '44444444-4444-4444-8444-444444444441',
   'fixture-att-1', 'ticket.pdf', 'application/pdf', 1234,
   '11111111-1111-4111-8111-111111111111/55555555-5555-4555-8555-555555555555/ticket.pdf',
   '2026-05-30 08:16:30', 'stored', 1, 3);

INSERT INTO public.events (id, user_id, title, start_datetime, end_datetime, all_day, location, description,
  created_at, updated_at, importance, review_status) VALUES
  ('66666666-6666-4666-8666-666666666661', '11111111-1111-4111-8111-111111111111', 'School play',
   '2099-06-05 15:00:00', '2099-06-05 17:00:00', false, 'School hall', 'Bring the ticket',
   '2026-05-30 08:17:00', '2026-05-30 08:17:00', 'action_required', 'pending_review'),
  ('66666666-6666-4666-8666-666666666662', '11111111-1111-4111-8111-111111111111', 'Dentist',
   '2099-06-10 06:30:00', '2099-06-10 07:00:00', false, NULL, NULL,
   '2026-05-31 09:02:00', '2026-06-01 10:00:00', 'fyi', 'active');

INSERT INTO public.event_sources (id, event_id, email_id, source_type, extracted_data, created_at, source_origin) VALUES
  ('77777777-7777-4777-8777-777777777771', '66666666-6666-4666-8666-666666666661', '44444444-4444-4444-8444-444444444441',
   'new_invitation', '{"title": "School play"}', '2026-05-30 08:17:00', 'email'),
  ('77777777-7777-4777-8777-777777777772', '66666666-6666-4666-8666-666666666662', '44444444-4444-4444-8444-444444444442',
   'new_invitation', '{"title": "Dentist"}', '2026-05-31 09:02:00', 'email');

INSERT INTO public.global_limits (id, limit_type, default_limit, max_allowed, is_active, created_at, updated_at) VALUES
  ('00000000-0000-4000-8000-000000000001', 'llm_calls_daily', 100, 1000, true, '2026-01-01 00:00:00', '2026-01-01 00:00:00'),
  ('00000000-0000-4000-8000-000000000002', 'email_syncs_daily', 50, 500, true, '2026-01-01 00:00:00', '2026-01-01 00:00:00'),
  ('00000000-0000-4000-8000-000000000003', 'calendar_syncs_daily', 100, 1000, true, '2026-01-01 00:00:00', '2026-01-01 00:00:00');
