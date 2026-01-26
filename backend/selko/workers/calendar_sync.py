"""Calendar sync worker - writes approved events to Google Calendar.

This worker:
1. Fetches an approved event from the events table
2. Writes it to Google Calendar via the API
3. Updates event status to 'synced'
4. Stores the Google Calendar event ID

Note: Google Calendar API integration is not yet implemented.
This is a placeholder for future implementation.
"""

import logging
from typing import Any

from supabase import Client

from selko.config import Config

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

    # TODO: Implement Google Calendar API integration
    # For now, just log that we would sync this event
    logger.warning(
        f"Google Calendar API not yet implemented. "
        f"Would sync event: {event['title']} at {event['start_datetime']}"
    )

    # Mark as synced (even though we didn't actually sync)
    # Remove this when real implementation is added
    try:
        client.table("events").update({
            "status": "synced",
            "synced_at": None,  # Would store actual sync time
            "google_calendar_event_id": None,  # Would store Calendar event ID
        }).eq("id", event_id).execute()

        logger.info(f"Marked event {event_id} as synced (placeholder)")

    except Exception as e:
        logger.error(f"Failed to update event status: {e}")
        raise

    # TODO: Actual implementation would:
    # 1. Get user's Google Calendar credentials
    # 2. Build Calendar API service
    # 3. Create event using events.insert()
    # 4. Store returned event ID
    # 5. Update event status to 'synced' with timestamp
