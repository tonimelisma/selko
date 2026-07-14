# Backlog

Future enhancements for Selko, documented for prioritization.

## Photo Library Ingestion (Parked)

Photo-library ingestion is parked because Google Photos library-wide read access was revoked. The restoration design, including a future OneDrive path, lives in [`docs/specs/onedrive-photo-ingestion.md`](specs/onedrive-photo-ingestion.md).

## Embedded Images in Emails

~~Extract inline images from HTML email bodies before sending to Gemini.~~ **Done** — all image types (linked, inline/CID, data URI) are now downloaded and stored at sync time. LLM processing loads from local storage only.

## Two-Way Calendar Sync

Detect drift between Selko events and Google Calendar. If a user edits an event directly in Google Calendar, Selko should detect the change and update its local record (or flag the conflict). Currently sync is one-way: Selko → Google Calendar.

## .ics File Direct Parsing

Parse `.ics` (iCalendar) file attachments directly without LLM. These files contain structured event data that can be parsed deterministically, saving LLM tokens and improving accuracy.

## Attachment Text Extraction

Pre-extract text from PDF attachments using OCR/text extraction before sending to LLM. This could reduce token usage by sending extracted text instead of raw PDF bytes, while still falling back to multimodal analysis for image-heavy PDFs.

## ~~Refactor `process_email_for_events()`~~ **Done**

~~The 130-line function in `events.py` does sender validation, LLM extraction, deduplication, and DB updates all in one. Break into smaller, testable steps: `should_skip_sender()`, `extract_and_deduplicate_events()`, `save_new_events()`.~~ Extracted 4 helpers: `mark_email_status()`, `should_skip_email()`, `normalize_event_data()`, `save_extracted_events()`. Orchestrator slimmed to ~35 lines. Added 20 unit tests in `test_events_refactor.py`.

## ~~Standardize API Error Responses~~

~~API routes use inconsistent error patterns: some return user-friendly messages, others pass raw exception text, others use generic strings. Create an `ErrorDetail` schema with `code`, `message`, `detail` fields and standardize all endpoints.~~ **Done** — added `ErrorCode` constants and `error_detail()` helper in `schemas/common.py`. All route files now use standardized `{"error": code, "detail": message}` responses. Security fix: replaced `str(e)` leaks in `calendars.py` and `health.py` with safe messages.

## ~~Add `body_text`/`body_html` to `EmailResponse` Schema~~ **Won't do**

~~Database stores `body_text` and `body_html` (migration `20260215000001`) and backend uses them for LLM processing, but `EmailResponse` schema omits them. API clients can't access full email bodies.~~ `EmailResponse` isn't used by any API endpoint — the 3 email routes return other schemas, and the frontend queries Supabase directly. Adding fields to an unused schema is a no-op.

## ~~Add `scheduled_tasks.py` Unit Tests~~ **Done**

~~`scheduled_tasks.py` service lacks a dedicated unit test file — only tested indirectly via integration tests. Add unit tests for `enqueue_scheduled_task()`, `claim_scheduled_task()`, `complete_scheduled_task()`, `fail_scheduled_task()`.~~

## Remove Unused Email Flag Fields from Schema

~~`EmailResponse` includes boolean flags (`is_social`, `is_updates`, `is_forums`, `is_important`, `is_starred`, `is_unread`) that are computed by DB triggers but never queried or displayed. Remove from schema and optionally drop trigger computation.~~ **Done** — removed `is_social`, `is_updates`, `is_forums`, `is_primary`, `is_important`, `is_starred` from `EmailResponse`. Kept `is_spam`, `is_trash`, `is_promotions`, `is_unread` (actively filtered in frontend). DB columns and triggers remain unchanged.

## ~~Deprecate `gemini_model` Config Field~~ **Done**

~~`config.py` has `gemini_model` (backward compat) alongside `llm_model` + `llm_provider`. Plan migration: rename env var, add deprecation warning, update all deployments.~~ Removed `gemini_model` field from `Config` and the backward-compat fallback in `create_provider()`. The `llm_model` + `llm_provider` fields with `PROVIDER_DEFAULT_MODEL` handle all cases.

## ~~Document `llm_call_log` Table in Database Schema~~ **Done**

~~The `llm_call_log` table (migration `20260130000001`, updated by `20260215000002`) is not documented in `docs/database-schema.md`. Add table definition including the `provider` column.~~
