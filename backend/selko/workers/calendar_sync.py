"""Calendar sync worker - writes approved events to Google Calendar.

This worker:
1. Receives a full event record (claimed via status-based polling)
2. Writes it to Google Calendar via the API
3. Returns the Google Calendar event ID

Note: The worker pool handles status updates (synced/sync_failed).
"""

import asyncio
import logging
from typing import Any

from supabase import Client

from selko.config import Config
from selko.services.calendars import (
    cancel_event_to_calendar,
    sync_event_to_calendar,
    CalendarsError,
)

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

    # Sync to Google Calendar using the calendars service (off event loop)
    try:
        google_event_id = await asyncio.to_thread(
            sync_event_to_calendar, client, user_id, event_id,
            expected_provider_revision=event.get("expected_provider_revision"),
            force_overwrite=bool(event.get("force_overwrite")),
        )
        logger.info(f"Synced event {event_id} to Google Calendar: {google_event_id}")
        return google_event_id
    except CalendarsError as e:
        logger.error(f"Failed to sync event {event_id} to Google Calendar: {e}")
        raise


async def cancel_event(
    client: Client,
    config: Config,
    event: dict[str, Any],
) -> None:
    """Apply a queued cancellation through the calendar worker only."""
    del config
    event_id = event["id"]
    user_id = event["user_id"]
    logger.info("Cancelling event %s in Google Calendar", event_id)
    try:
        desired = event.get("calendar_work_desired_event") or {}
        await asyncio.to_thread(
            cancel_event_to_calendar,
            client,
            user_id,
            event_id,
            expected_provider_revision=event.get("expected_provider_revision"),
            force_overwrite=bool(event.get("force_overwrite")),
            delete_remote=bool(desired.get("delete_remote")),
        )
    except CalendarsError as exc:
        logger.error("Failed to cancel event %s in Google Calendar: %s", event_id, exc)
        raise
