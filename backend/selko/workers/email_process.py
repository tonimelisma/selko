"""Email process worker - extracts calendar events from emails using LLM.

This worker:
1. Fetches email and attachments from database
2. Calls Gemini LLM to extract calendar events
3. Creates events in the events table
4. Marks email as processed
"""

import logging
from typing import Any

from supabase import Client

from selko.config import Config
from selko.services.events import EventsError, process_email_for_events
from selko.services.gemini import get_gemini_client

logger = logging.getLogger(__name__)


async def process_email_process_job(
    client: Client,
    config: Config,
    job_id: str,
    payload: dict[str, Any],
) -> None:
    """Process an email_process job.

    Args:
        client: Supabase client (with service role).
        config: Application configuration.
        job_id: UUID of the job being processed.
        payload: Job payload with {email_id: str}.

    Raises:
        EventsError: If event extraction/processing fails.
    """
    email_id = payload.get("email_id")

    if not email_id:
        raise ValueError("Missing email_id in payload")

    logger.info(f"Processing email {email_id} for calendar events")

    # Get email metadata to determine user_id
    try:
        email_result = client.table("emails").select(
            "user_id, subject"
        ).eq("id", email_id).single().execute()

        email = email_result.data
        user_id = email["user_id"]
        subject = email.get("subject", "(no subject)")

    except Exception as e:
        raise EventsError(f"Failed to fetch email {email_id}: {e}") from e

    # Initialize Gemini client
    try:
        gemini_client = get_gemini_client(config)
    except Exception as e:
        raise EventsError(f"Failed to initialize Gemini: {e}") from e

    # Process email for events (this handles everything)
    try:
        result = process_email_for_events(
            client,
            gemini_client,
            email_id,
            user_id,
        )

        num_events = result.get("num_events", 0)
        num_new = result.get("num_new", 0)
        num_updated = result.get("num_updated", 0)
        skipped = result.get("skipped", False)

        if skipped:
            logger.info(f"Email {email_id} skipped (sender ignored)")
        elif num_events > 0:
            logger.info(
                f"Extracted {num_events} events from email '{subject}': "
                f"{num_new} new, {num_updated} updated"
            )
        else:
            logger.info(f"No events found in email '{subject}'")

    except EventsError as e:
        logger.error(f"Failed to process email {email_id}: {e}")
        raise
