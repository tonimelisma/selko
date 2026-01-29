"""Email process worker - extracts calendar events from emails using LLM.

This worker:
1. Receives a full email record (claimed via status-based polling)
2. Calls Gemini LLM to extract calendar events
3. Creates events in the events table

Note: The worker pool handles status updates (processed/failed).
"""

import logging
from typing import Any

from supabase import Client

from selko.config import Config
from selko.services.events import EventsError, process_email_for_events
from selko.services.gemini import get_gemini_client
from selko.services.llm_logging import LLMLoggingService

logger = logging.getLogger(__name__)


async def process_email(
    client: Client,
    config: Config,
    email: dict[str, Any],
) -> None:
    """Process an email for calendar event extraction.

    This is called by the worker pool after claiming an email.
    Status updates are handled by the worker pool.

    Args:
        client: Supabase client (with service role).
        config: Application configuration.
        email: Full email record (from claim_pending_email).

    Raises:
        EventsError: If event extraction/processing fails.
    """
    email_id = email["id"]
    user_id = email["user_id"]
    subject = email.get("subject", "(no subject)")

    logger.info(f"Processing email {email_id} for calendar events: {subject[:50]}")

    # Initialize Gemini client
    try:
        gemini_client = get_gemini_client(config)
    except Exception as e:
        raise EventsError(f"Failed to initialize Gemini: {e}") from e

    # Create LLM logging service (worker uses service role client)
    logging_service = LLMLoggingService(client)

    # Process email for events (this handles everything)
    try:
        result = process_email_for_events(
            client,
            gemini_client,
            email_id,
            user_id,
            logging_service=logging_service,
        )

        num_events = result.get("num_events", 0)
        num_new = result.get("num_new", 0)
        num_updated = result.get("num_updated", 0)
        skipped = result.get("skipped", False)

        if skipped:
            logger.info(f"Email {email_id} skipped (sender ignored)")
        elif num_events > 0:
            logger.info(
                f"Extracted {num_events} events from email '{subject[:50]}': "
                f"{num_new} new, {num_updated} updated"
            )
        else:
            logger.info(f"No events found in email '{subject[:50]}'")

    except EventsError as e:
        logger.error(f"Failed to process email {email_id}: {e}")
        raise


# Keep old function signature for backwards compatibility with existing tests
async def process_email_process_job(
    client: Client,
    config: Config,
    job_id: str,
    payload: dict[str, Any],
) -> None:
    """Legacy function for processing email_process jobs.

    This function is kept for backwards compatibility during the transition.
    New code should use process_email() directly.

    Args:
        client: Supabase client (with service role).
        config: Application configuration.
        job_id: UUID of the job being processed (unused in new architecture).
        payload: Job payload with {email_id: str}.

    Raises:
        EventsError: If event extraction/processing fails.
    """
    email_id = payload.get("email_id")

    if not email_id:
        raise ValueError("Missing email_id in payload")

    # Fetch the full email record
    try:
        email_result = client.table("emails").select("*").eq(
            "id", email_id
        ).single().execute()

        email = email_result.data

    except Exception as e:
        raise EventsError(f"Failed to fetch email {email_id}: {e}") from e

    # Process using new function
    await process_email(client, config, email)
