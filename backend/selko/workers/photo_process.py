"""Photo process worker - extracts calendar events from photos using LLM.

This worker:
1. Receives a photo record (claimed via status-based polling)
2. Downloads the photo from Google Photos
3. Uploads to Supabase Storage
4. Calls LLM to analyze the photo for calendar-relevant content
5. Creates events from extracted data

Note: The worker pool handles status updates (processed/failed).
"""

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from supabase import Client

from selko.api.schemas.calendar import CalendarEventExtraction, EventExtractionResponse
from selko.config import Config
from selko.services.event_processing import looks_like_json_schema
from selko.services.events import save_extracted_events
from selko.services.google_photos import (
    PhotosError,
    download_photo_bytes,
    get_credentials,
    build_service,
)
from selko.services.llm_gateway import LLMGatewayError, create_llm_gateway
from selko.services.llm_logging import LLMLoggingService, LLMOperationType
from selko.services.llm_provider import ContentPart, ImageContent

logger = logging.getLogger(__name__)


def _build_photo_prompt(photo: dict[str, Any], current_date: str) -> str:
    """Build the system prompt for photo event extraction.

    Args:
        photo: Photo record dict with metadata.
        current_date: Current date in YYYY-MM-DD format.

    Returns:
        Formatted prompt string.
    """
    filename = photo.get("filename", "(unknown)")
    description = photo.get("description", "")
    date_taken = photo.get("date_taken", "")

    prompt = f"""You are an expert at extracting calendar events from photos.

**Current Date:** {current_date}

**Photo Metadata:**
- Filename: {filename}
- Description: {description}
- Date Taken: {date_taken}

**Instructions:**
1. Analyze this photo for any calendar-relevant content
2. Look for: event tickets, concert/theater tickets, boarding passes, event posters,
   flyers, invitations, schedules, conference badges, appointment cards, school calendars,
   sports schedules, restaurant reservations, and any other content showing event details
3. For each event found, extract:
   - Title (clear, concise event name)
   - Start date/time (parse any visible dates, use photo date as context)
   - End date/time (if visible)
   - Location (venue name, address, gate/seat info)
   - Full description with all relevant details visible in the photo
   - Whether it's an all-day event (true/false)
   - Importance: "action_required" (events requiring user action) or "fyi" (informational)

**Important:**
- If NO calendar events are found in the photo, set events_found=false and return empty events list
- Most photos will NOT contain calendar events - only extract when clearly visible
- Parse dates carefully using the current date and photo date as context
- For tickets/boarding passes: extract venue, date, time, seat/gate info
- For flyers/posters: extract event name, date, time, location
- For invitations: extract event details, RSVP info, location

**NOT events (do NOT extract):**
- Personal photos of people, landscapes, food, etc. without event details
- Screenshots of social media without specific event information
- General informational content without dates or times
- Receipts or financial documents (unless showing appointment details)
"""
    return prompt


async def process_photo(
    client: Client,
    config: Config,
    photo: dict[str, Any],
) -> dict[str, Any]:
    """Process a photo for calendar event extraction.

    Runs blocking Google/LLM/DB work in a thread so the API event loop
    stays responsive.
    """
    return await asyncio.to_thread(_process_photo_sync, client, config, photo)


def _process_photo_sync(
    client: Client,
    config: Config,
    photo: dict[str, Any],
) -> dict[str, Any]:
    """Synchronous photo processing body (run via asyncio.to_thread)."""
    photo_id = photo["id"]
    user_id = photo["user_id"]
    filename = photo.get("filename", "(unknown)")

    logger.info(f"Processing photo {photo_id}: {filename[:50]}")

    # Step 1: Get Google Photos credentials and download photo
    creds = get_credentials(client, config, user_id=user_id)
    if not creds:
        raise PhotosError("No Google Photos credentials found")

    service = build_service(creds)

    # Get fresh baseUrl (they expire after ~60 minutes)
    try:
        media_item = service.mediaItems().get(
            mediaItemId=photo["google_photo_id"]
        ).execute()
    except Exception as e:
        raise PhotosError(f"Failed to get media item: {e}") from e

    photo_bytes = download_photo_bytes(media_item)

    # Step 2: Upload to Supabase Storage
    content_hash = hashlib.sha256(photo_bytes).hexdigest()
    safe_filename = os.path.basename(filename).replace("..", "")[:100]
    unique_id = uuid4().hex[:12]
    storage_path = f"{user_id}/photos/{unique_id}_{safe_filename}"

    try:
        mime_type = photo.get("mime_type", "image/jpeg")
        client.storage.from_("attachments").upload(
            path=storage_path,
            file=photo_bytes,
            file_options={"content-type": mime_type},
        )
        logger.debug(f"Uploaded photo to storage: {storage_path}")
    except Exception as e:
        raise PhotosError(f"Failed to upload photo to storage: {e}") from e

    # Update photo record with storage path and hash
    try:
        client.table("photos").update({
            "storage_path": storage_path,
            "content_hash": content_hash,
        }).eq("id", photo_id).execute()
    except Exception as e:
        logger.warning(f"Failed to update photo storage path: {e}")

    # Step 3: Build LLM prompt
    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = _build_photo_prompt(photo, current_date)

    # Step 4: Call LLM with photo
    logging_service = LLMLoggingService(client)
    gateway = create_llm_gateway(config, logging_service=logging_service, quota_service=None)
    gateway.for_user(user_id)

    content_parts: list[ContentPart] = [
        prompt,
        ImageContent(
            data=photo_bytes,
            mime_type=photo.get("mime_type", "image/jpeg"),
        ),
    ]

    json_schema = EventExtractionResponse.model_json_schema()

    try:
        response = gateway.call(
            operation=LLMOperationType.EXTRACT_EVENTS,
            contents=content_parts,
            json_schema=json_schema,
            max_retries=3,
        )

        parsed = json.loads(response.text)
        if looks_like_json_schema(parsed):
            raise LLMGatewayError(
                "LLM returned JSON schema instead of extraction data"
            )
        llm_result = EventExtractionResponse.model_validate(parsed)

        logger.info(
            f"Photo extraction complete: {len(llm_result.events)} events found "
            f"(events_found={llm_result.events_found})"
        )

    except LLMGatewayError:
        raise
    except Exception as e:
        raise LLMGatewayError(f"Failed to extract events from photo: {e}") from e

    # Step 5: Save extracted events
    result: dict[str, Any] = {
        "num_events": 0,
        "num_new": 0,
        "num_updated": 0,
    }

    if not llm_result.events_found or not llm_result.events:
        logger.info(f"No events found in photo '{filename[:50]}'")
        return result

    # Build extraction object for save_extracted_events
    extraction = CalendarEventExtraction(
        email_message_id="",  # Not from email
        email_date=photo.get("date_taken") or None,
        sender_name=None,
        sender_email="",
        events_found=llm_result.events_found,
        events=llm_result.events,
    )

    # Create event source link with source_origin='google_photos'
    # We need to save events and link them to the photo
    for event in extraction.events:
        from selko.services.events import normalize_event_data, create_event

        event_data = normalize_event_data(event)
        event_id = _create_photo_event(client, user_id, event_data, photo_id)
        result["num_new"] += 1

    result["num_events"] = len(extraction.events)

    logger.info(
        f"Extracted {result['num_events']} events from photo '{filename[:50]}': "
        f"{result['num_new']} new"
    )

    return result


def _create_photo_event(
    client: Client,
    user_id: str,
    event_data: dict[str, Any],
    photo_id: str,
) -> str:
    """Create a new event from photo extraction and link via event_sources.

    Args:
        client: Authenticated Supabase client.
        user_id: UUID of user.
        event_data: Normalized event data.
        photo_id: UUID of source photo.

    Returns:
        UUID of created event.
    """
    # Create event record
    event_result = client.table("events").insert({
        "user_id": user_id,
        "title": event_data.get("title"),
        "start_datetime": event_data.get("start_datetime"),
        "end_datetime": event_data.get("end_datetime"),
        "all_day": event_data.get("all_day", False),
        "location": event_data.get("location"),
        "description": event_data.get("description"),
        "importance": event_data.get("importance", "action_required"),
        "status": "pending_review",
    }).execute()

    if not event_result.data:
        raise PhotosError(f"Failed to create event from photo {photo_id}: no data returned")
    event_id = event_result.data[0]["id"]

    # Create event_source link with google_photos origin
    client.table("event_sources").insert({
        "event_id": event_id,
        "source_origin": "google_photos",
        "source_type": "new_invitation",
        "extracted_data": {
            **event_data,
            "photo_id": photo_id,
        },
        "event_snapshot_before": None,
    }).execute()

    logger.info(f"Created event {event_id} from photo {photo_id}")
    return event_id
