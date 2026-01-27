"""Calendar sync worker - writes approved events to Google Calendar.

This worker:
1. Fetches an approved event from the events table
2. Writes it to Google Calendar via the API
3. Updates event status to 'synced'
4. Stores the Google Calendar event ID
"""

import logging
from typing import Any

from supabase import Client

from selko.config import Config
from selko.services.calendars import sync_event_to_calendar, CalendarsError

logger = logging.getLogger(__name__)


async def process_calendar_sync_job(
    client: Client,
    config: Config,
    job_id: str,
    payload: dict[str, Any],
) -> None:
    """Process a calendar_sync job.

    Args:
        client: Supabase client (with service role).
        config: Application configuration.
        job_id: UUID of the job being processed.
        payload: Job payload with {event_id: str}.

    Raises:
        NotImplementedError: Google Calendar API not yet implemented.
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

    # Sync to Google Calendar using the calendars service
    try:
        google_event_id = sync_event_to_calendar(client, event["user_id"], event_id)
        logger.info(f"Synced event {event_id} to Google Calendar: {google_event_id}")
    except CalendarsError as e:
        logger.error(f"Failed to sync event {event_id} to Google Calendar: {e}")
        raise
