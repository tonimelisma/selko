"""Email process worker - extracts calendar events from emails using LLM.

This worker:
1. Receives a full email record (claimed via status-based polling)
2. Calls Gemini LLM to extract calendar events
3. Creates events in the events table

Note: The worker pool handles status updates (processed/failed).
"""

import asyncio
import logging
from typing import Any

from selko.config import Config
from selko.db.connection import Database
from selko.services.events import EventsError, process_email_for_events
from selko.services.llm_gateway import create_llm_gateway
from selko.services.llm_logging import LLMLoggingService

logger = logging.getLogger(__name__)


async def process_email(
    client: Database,
    config: Config,
    email: dict[str, Any],
) -> dict[str, Any]:
    """Process an email for calendar event extraction.

    This is called by the worker pool after claiming an email.
    Status updates are handled by the worker pool — EXCEPT when
    process_email_for_events already left the email in a terminal skipped
    state (sender-ignored, calendar invite). The returned ``skipped`` flag
    signals that to the caller, which must not overwrite it back to
    "processed".

    Args:
        client: The process database.
        config: Application configuration.
        email: Full email record (from claim_pending_email).

    Returns:
        The result dict from process_email_for_events (num_events, num_new,
        num_updated, and skipped when the email was left in a terminal
        skipped state rather than needing the pool to mark it processed).

    Raises:
        EventsError: If event extraction/processing fails.
    """
    email_id = email["id"]
    user_id = email["user_id"]
    subject = email.get("subject", "(no subject)")

    logger.info(f"Processing email {email_id} for calendar events: {subject[:50]}")

    # Create gateway with logging service
    # Note: Workers don't enforce quotas (that's done at the API level)
    logging_service = LLMLoggingService(client)
    gateway = create_llm_gateway(config, logging_service=logging_service, quota_service=None)

    # Run sync LLM/DB work off the event loop so HTTP stays responsive
    try:
        result = await asyncio.to_thread(
            process_email_for_events,
            client,
            gateway,
            email_id,
            user_id,
            config,
            email,  # Inc1: pass claimed row to skip re-fetch
        )

        num_events = result.get("num_events", 0)
        num_new = result.get("num_new", 0)
        num_updated = result.get("num_updated", 0)
        skipped = result.get("skipped", False)

        if skipped:
            logger.info(f"Email {email_id} skipped")
        elif num_events > 0:
            logger.info(
                f"Extracted {num_events} events from email '{subject[:50]}': "
                f"{num_new} new, {num_updated} updated"
            )
        else:
            logger.info(f"No events found in email '{subject[:50]}'")

        return result

    except EventsError as e:
        logger.error(f"Failed to process email {email_id}: {e}")
        raise


# Keep old function signature for backwards compatibility with existing tests
