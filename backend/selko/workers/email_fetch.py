"""Email fetch worker - fetches emails from Gmail.

This worker:
1. Fetches new emails from Gmail for a user
2. Stores them in the emails table with processing_status='pending'

Emails are automatically picked up by the worker pool for LLM processing
because they're saved with processing_status='pending'.
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
from selko.services.scheduled_tasks import enqueue_scheduled_task

logger = logging.getLogger(__name__)


async def process_email_fetch_task(
    client: Client,
    config: Config,
    payload: dict[str, Any],
) -> None:
    """Process an email_fetch scheduled task.

    Args:
        client: Supabase client (with service role).
        config: Application configuration.
        payload: Task payload with {user_id: str, max_emails: int}.

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
    # Emails are saved with processing_status='pending' (default)
    # The worker pool will automatically pick them up for LLM processing
    try:
        parsed = [parse_gmail_message(msg) for msg in messages]
        saved_records = save_emails(client, parsed, user_id=user_id)
        logger.info(
            f"Saved {len(saved_records)} emails for user {user_id} "
            f"(will be auto-processed by workers)"
        )
    except EmailError as e:
        logger.error(f"Error saving emails for user {user_id}: {e}")
        raise


# Keep old function signature for backwards compatibility
async def process_email_fetch_job(
    client: Client,
    config: Config,
    job_id: str,
    payload: dict[str, Any],
) -> None:
    """Legacy function for processing email_fetch jobs.

    This function is kept for backwards compatibility during the transition.
    New code should use process_email_fetch_task() directly.
    """
    await process_email_fetch_task(client, config, payload)


async def schedule_email_fetches() -> None:
    """Scheduler function that creates email_fetch tasks for all users.

    Called by APScheduler every 15 minutes. Creates one email_fetch scheduled task
    per user who has an active Gmail integration, skipping users who already have
    a pending or processing task.
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

        # Find users who already have a pending or processing email_fetch task
        existing_result = client.table("scheduled_tasks").select(
            "user_id"
        ).eq(
            "task_type", "email_fetch"
        ).in_(
            "status", ["pending", "processing"]
        ).execute()

        users_with_existing_task = {row["user_id"] for row in existing_result.data}

        # Create email_fetch scheduled task only for users without an existing one
        tasks_created = 0
        tasks_skipped = 0
        for user_id in users:
            if user_id in users_with_existing_task:
                tasks_skipped += 1
                continue
            try:
                enqueue_scheduled_task(
                    client,
                    user_id=user_id,
                    task_type="email_fetch",
                    payload={"user_id": user_id, "max_emails": 50},
                )
                tasks_created += 1
            except Exception as e:
                logger.error(f"Failed to enqueue email_fetch for user {user_id}: {e}")

        if tasks_skipped:
            logger.info(
                f"Scheduled email fetch for {tasks_created} users "
                f"({tasks_skipped} skipped — already queued)"
            )
        else:
            logger.info(f"Scheduled email fetch for {tasks_created} users")

    except Exception as e:
        logger.error(f"Failed to schedule email fetches: {e}", exc_info=True)
