"""Calendar sync worker - writes approved events to Google Calendar.

This worker:
1. Receives a full event record (claimed via status-based polling)
2. Writes it to Google Calendar via the API
3. Returns the Google Calendar event ID

Note: The worker pool handles status updates (synced/sync_failed).
"""

import logging
from typing import Any

from supabase import Client

from selko.config import Config
from selko.services.calendars import sync_event_to_calendar, CalendarsError

logger = logging.getLogger(__name__)


async def sync_event(
    client: Client,
    config: Config,
    event: dict[str, Any],
) -> str:
    """Sync an event to Google Calendar.

    This is called by the worker pool after claiming an approved event.
    Status updates are handled by the worker pool.

    Args:
        client: Supabase client (with service role).
        config: Application configuration.
        event: Full event record (from claim_approved_event).

    Returns:
        Google Calendar event ID.

    Raises:
        CalendarsError: If sync fails.
    """
    event_id = event["id"]
    user_id = event["user_id"]
    title = event.get("title", "(no title)")

    logger.info(f"Syncing event {event_id} to Google Calendar: {title[:50]}")

    # Sync to Google Calendar using the calendars service
    try:
        google_event_id = sync_event_to_calendar(client, user_id, event_id)
        logger.info(f"Synced event {event_id} to Google Calendar: {google_event_id}")
        return google_event_id
    except CalendarsError as e:
        logger.error(f"Failed to sync event {event_id} to Google Calendar: {e}")
        raise


# Keep old function signature for backwards compatibility with existing tests
async def process_calendar_sync_job(
    client: Client,
    config: Config,
    job_id: str,
    payload: dict[str, Any],
) -> None:
    """Legacy function for processing calendar_sync jobs.

    This function is kept for backwards compatibility during the transition.
    New code should use sync_event() directly.

    Args:
        client: Supabase client (with service role).
        config: Application configuration.
        job_id: UUID of the job being processed (unused in new architecture).
        payload: Job payload with {event_id: str}.

    Raises:
        CalendarsError: If sync fails.
    """
    event_id = payload.get("event_id")

    if not event_id:
        raise ValueError("Missing event_id in payload")

    logger.info(f"Syncing event {event_id} to Google Calendar")

    # Fetch event from database
    try:
        event_result = client.table("events").select(
            "*"
        ).eq("id", event_id).single().execute()

        event = event_result.data

        if event["status"] != "approved":
            logger.warning(
                f"Event {event_id} is not approved (status: {event['status']}), "
                "skipping calendar sync"
            )
            return

    except Exception as e:
        raise ValueError(f"Failed to fetch event {event_id}: {e}") from e

    # Sync to Google Calendar
    google_event_id = await sync_event(client, config, event)

    # Update event status (legacy - new architecture handles this in pool.py)
    client.table("events").update({
        "status": "synced",
        "google_calendar_event_id": google_event_id,
    }).eq("id", event_id).execute()
