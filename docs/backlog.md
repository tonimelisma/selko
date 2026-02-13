# Backlog

Future enhancements for Selko, documented for prioritization.

## Google Photos Integration

Scan Google Photos for event-related images (tickets, posters, flyers) and extract calendar event data using Gemini multimodal analysis. Requires `google_photos` OAuth scope and a new `event_sources.source_origin = 'google_photos'` workflow.

## Embedded Images in Emails

Extract inline images from HTML email bodies before sending to Gemini. Currently only standalone attachments are processed. Embedded images (e.g., event flyers in newsletters) may contain event details.

## Two-Way Calendar Sync

Detect drift between Selko events and Google Calendar. If a user edits an event directly in Google Calendar, Selko should detect the change and update its local record (or flag the conflict). Currently sync is one-way: Selko → Google Calendar.

## .ics File Direct Parsing

Parse `.ics` (iCalendar) file attachments directly without LLM processing. These files contain structured event data that can be parsed deterministically, saving LLM tokens and improving accuracy.

## Configurable Per-User Reprocess Window

Allow users to configure how far back to reprocess emails when un-ignoring a sender. Currently hardcoded to 30 days. Some users may want a longer window (e.g., 90 days) or shorter (7 days) depending on their email volume.

## Attachment Text Extraction

Pre-extract text from PDF attachments using OCR/text extraction before sending to Gemini. This could reduce token usage by sending extracted text instead of raw PDF bytes, while still falling back to multimodal analysis for image-heavy PDFs.
