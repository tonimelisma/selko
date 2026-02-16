# Backlog

Future enhancements for Selko, documented for prioritization.

## Google Photos Integration

Scan Google Photos for event-related images (tickets, posters, flyers) and extract calendar event data using LLM multimodal analysis. Requires `google_photos` OAuth scope and a new `event_sources.source_origin = 'google_photos'` workflow.

## Embedded Images in Emails

~~Extract inline images from HTML email bodies before sending to Gemini.~~ **Done** — all image types (linked, inline/CID, data URI) are now downloaded and stored at sync time. LLM processing loads from local storage only.

## Two-Way Calendar Sync

Detect drift between Selko events and Google Calendar. If a user edits an event directly in Google Calendar, Selko should detect the change and update its local record (or flag the conflict). Currently sync is one-way: Selko → Google Calendar.

## .ics File Direct Parsing

Parse `.ics` (iCalendar) file attachments directly without LLM. These files contain structured event data that can be parsed deterministically, saving LLM tokens and improving accuracy.

## Attachment Text Extraction

Pre-extract text from PDF attachments using OCR/text extraction before sending to LLM. This could reduce token usage by sending extracted text instead of raw PDF bytes, while still falling back to multimodal analysis for image-heavy PDFs.

## Refactor `process_email_for_events()`

The 130-line function in `events.py` does sender validation, LLM extraction, deduplication, and DB updates all in one. Break into smaller, testable steps: `should_skip_sender()`, `extract_and_deduplicate_events()`, `save_new_events()`.

## Standardize API Error Responses

API routes use inconsistent error patterns: some return user-friendly messages, others pass raw exception text, others use generic strings. Create an `ErrorDetail` schema with `code`, `message`, `detail` fields and standardize all endpoints.

## Add `body_text`/`body_html` to `EmailResponse` Schema

Database stores `body_text` and `body_html` (migration `20260215000001`) and backend uses them for LLM processing, but `EmailResponse` schema omits them. API clients can't access full email bodies.

## Add `scheduled_tasks.py` Unit Tests

`scheduled_tasks.py` service lacks a dedicated unit test file — only tested indirectly via integration tests. Add unit tests for `enqueue_scheduled_task()`, `claim_scheduled_task()`, `complete_scheduled_task()`, `fail_scheduled_task()`.

## Remove Unused Email Flag Fields from Schema

`EmailResponse` includes boolean flags (`is_social`, `is_updates`, `is_forums`, `is_important`, `is_starred`, `is_unread`) that are computed by DB triggers but never queried or displayed. Remove from schema and optionally drop trigger computation.

## Deprecate `gemini_model` Config Field

`config.py` has `gemini_model` (backward compat) alongside `llm_model` + `llm_provider`. Plan migration: rename env var, add deprecation warning, update all deployments.

## Document `llm_call_log` Table in Database Schema

The `llm_call_log` table (migration `20260130000001`, updated by `20260215000002`) is not documented in `docs/database-schema.md`. Add table definition including the `provider` column.
