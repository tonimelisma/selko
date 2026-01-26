"""Email fetch worker - fetches emails from Gmail and creates process jobs.

This worker:
1. Fetches new emails from Gmail for a user
2. Stores them in the emails table
3. Creates email_process jobs for each email
"""

import logging
from typing import Any

from supabase import Client

from selko.config import Config
from selko.services.emails import EmailError, parse_gmail_message, save_emails
from selko.services.gmail import (
    GmailError,
    build_service,
    fetch_messages,
    get_credentials,
)
from selko.services.jobs import enqueue_job

logger = logging.getLogger(__name__)


async def process_email_fetch_job(
    client: Client,
    config: Config,
    job_id: str,
    payload: dict[str, Any],
) -> None:
    """Process an email_fetch job.

    Args:
        client: Supabase client (with service role).
        config: Application configuration.
        job_id: UUID of the job being processed.
        payload: Job payload with {user_id: str, max_emails: int}.

    Raises:
        GmailError: If Gmail API calls fail.
        EmailError: If email processing fails.
    """
    user_id = payload.get("user_id")
    max_emails = payload.get("max_emails", 50)

    if not user_id:
        raise ValueError("Missing user_id in payload")

    logger.info(f"Fetching up to {max_emails} emails for user {user_id}")

    # Get Gmail credentials for this user
    creds = get_credentials(client, config, user_id=user_id)
    if not creds:
        logger.warning(f"No Gmail integration found for user {user_id}")
        return

    # Build Gmail service and fetch messages
    try:
        service = build_service(creds)
        messages = fetch_messages(service, max_results=max_emails)
    except GmailError as e:
        logger.error(f"Error fetching emails for user {user_id}: {e}")
        raise

    if not messages:
        logger.info(f"No new emails found for user {user_id}")
        return

    # Parse and save emails
    try:
        parsed = [parse_gmail_message(msg) for msg in messages]
        saved_records = save_emails(client, parsed, user_id=user_id)
        logger.info(f"Saved {len(saved_records)} emails for user {user_id}")
    except EmailError as e:
        logger.error(f"Error saving emails for user {user_id}: {e}")
        raise

    # Create email_process jobs for each saved email
    jobs_created = 0
    for record in saved_records:
        email_id = record["id"]

        try:
            enqueue_job(
                client,
                user_id=user_id,
                job_type="email_process",
                payload={"email_id": email_id},
                priority=0,
            )
            jobs_created += 1
        except Exception as e:
            logger.error(f"Failed to enqueue email_process job for {email_id}: {e}")

    logger.info(f"Created {jobs_created} email_process jobs for user {user_id}")


async def schedule_email_fetches() -> None:
    """Scheduler function that creates email_fetch jobs for all users.

    Called by APScheduler every 5 minutes. Creates one email_fetch job
    per user who has an active Gmail integration.
    """
    from selko.config import load_config
    from selko.services.auth import get_service_client

    config = load_config()
    client = get_service_client(config)

    try:
        # Get all users with active Gmail integrations
        result = client.table("integrations").select(
            "user_id"
        ).eq("provider", "gmail").eq("status", "active").execute()

        users = {row["user_id"] for row in result.data}

        if not users:
            logger.debug("No users with active Gmail integrations")
            return

        # Create email_fetch job for each user
        jobs_created = 0
        for user_id in users:
            try:
                enqueue_job(
                    client,
                    user_id=user_id,
                    job_type="email_fetch",
                    payload={"user_id": user_id, "max_emails": 50},
                    priority=0,
                )
                jobs_created += 1
            except Exception as e:
                logger.error(f"Failed to enqueue email_fetch for user {user_id}: {e}")

        logger.info(f"Scheduled email fetch for {jobs_created} users")

    except Exception as e:
        logger.error(f"Failed to schedule email fetches: {e}", exc_info=True)
