#!/usr/bin/env python3
"""CLI for processing emails into calendar events.

Processes emails from the database using the Gemini LLM to extract
calendar events, handling deduplication and saving to the events table.
"""

import argparse
import logging
import sys

from supabase import create_client

from selko.config import add_logging_arguments, load_config
from selko.logging import setup_logging
from selko.services.auth import AuthenticationError, get_authenticated_client, get_current_user_id
from selko.services.events import EventsError, process_email_for_events
from selko.services.llm_gateway import LLMGateway, LLMGatewayError
from selko.services.llm_logging import LLMLoggingService

logger = logging.getLogger(__name__)


def process_single_email(supabase_client, gateway, user_id: str, email_id: str):
    """Process a single email by ID.

    Args:
        supabase_client: Authenticated Supabase client.
        gateway: LLMGateway instance.
        user_id: UUID of the authenticated user.
        email_id: UUID of the email to process.
    """
    # Fetch email details for display
    email_result = (
        supabase_client.table("emails")
        .select("subject, from_email, processing_status")
        .eq("id", email_id)
        .single()
        .execute()
    )

    if not email_result.data:
        logger.error(f"Email not found: {email_id}")
        sys.exit(1)

    email = email_result.data
    subject = email.get("subject", "(no subject)")
    status = email.get("processing_status", "unknown")

    logger.info(f"Processing email: {subject[:50]}...")
    logger.info(f"  Current status: {status}")

    try:
        result = process_email_for_events(
            supabase_client=supabase_client,
            gateway=gateway,
            email_id=email_id,
            user_id=user_id,
        )

        if result.get("skipped"):
            logger.info("  Skipped (sender is ignored)")
        else:
            logger.info(f"  Events extracted: {result['num_events']}")
            logger.info(f"  New events: {result['num_new']}")
            logger.info(f"  Updated events: {result['num_updated']}")

    except EventsError as e:
        logger.error(f"  Failed: {e}")
        sys.exit(1)


def process_recent_emails(supabase_client, gateway, user_id: str, max_emails: int):
    """Process recent emails in batch.

    Args:
        supabase_client: Authenticated Supabase client.
        gateway: LLMGateway instance.
        user_id: UUID of the authenticated user.
        max_emails: Maximum number of emails to process.
    """
    # Fetch recent emails that haven't been processed
    result = (
        supabase_client.table("emails")
        .select("id, subject, from_email, processing_status")
        .in_("processing_status", ["pending", "failed"])
        .order("date_sent", desc=True)
        .limit(max_emails)
        .execute()
    )

    if not result.data:
        logger.info("No pending emails to process")
        return

    emails = result.data
    logger.info(f"Processing {len(emails)} emails...")

    total_new = 0
    total_updated = 0
    total_skipped = 0
    total_failed = 0

    for email in emails:
        email_id = email["id"]
        subject = email.get("subject", "(no subject)")

        logger.info(f"\n{'='*60}")
        logger.info(f"Email: {subject[:50]}...")

        try:
            proc_result = process_email_for_events(
                supabase_client=supabase_client,
                gateway=gateway,
                email_id=email_id,
                user_id=user_id,
            )

            if proc_result.get("skipped"):
                logger.info("  Skipped (sender is ignored)")
                total_skipped += 1
            else:
                logger.info(f"  New: {proc_result['num_new']}, Updated: {proc_result['num_updated']}")
                total_new += proc_result["num_new"]
                total_updated += proc_result["num_updated"]

        except EventsError as e:
            logger.error(f"  Failed: {e}")
            total_failed += 1
            continue

    logger.info(f"\n{'='*60}")
    logger.info("SUMMARY")
    logger.info(f"  Emails processed: {len(emails)}")
    logger.info(f"  New events: {total_new}")
    logger.info(f"  Updated events: {total_updated}")
    logger.info(f"  Skipped (ignored sender): {total_skipped}")
    logger.info(f"  Failed: {total_failed}")


def main():
    parser = argparse.ArgumentParser(
        description="Process emails into calendar events using Gemini AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process a single email by ID
  uv run python -m cli.cli_process_emails --email-id <uuid>

  # Process 5 most recent pending emails
  uv run python -m cli.cli_process_emails --recent 5

  # Use staging environment
  ENVIRONMENT=staging uv run python -m cli.cli_process_emails --recent 10

  # Enable verbose logging
  uv run python -m cli.cli_process_emails -v --email-id <uuid>

Note:
  This CLI processes emails and SAVES events to the database.
  Use cli_extract_events for preview-only extraction (no database writes).
  Requires GEMINI_API_KEY, TEST_USER_EMAIL, and TEST_USER_PASSWORD in .env.
        """,
    )

    add_logging_arguments(parser)

    # Mutually exclusive source options
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--email-id",
        type=str,
        help="UUID of email in database to process",
    )
    source_group.add_argument(
        "--recent",
        type=int,
        metavar="N",
        help="Process N most recent pending emails",
    )

    args = parser.parse_args()

    setup_logging(verbose=args.verbose, quiet=args.quiet)
    config = load_config()

    # Authenticate with Supabase
    try:
        supabase_client = get_authenticated_client(config)
        user_id = get_current_user_id(supabase_client)
    except AuthenticationError as e:
        logger.error(f"Authentication failed: {e}")
        sys.exit(1)

    # Create LLM logging service with service role client
    logging_service = None
    if config.supabase_service_role_key:
        service_client = create_client(config.supabase_url, config.supabase_service_role_key)
        logging_service = LLMLoggingService(service_client)
        logger.debug("LLM call logging enabled")
    else:
        logger.warning("Service role key not configured, LLM call logging disabled")

    # Create LLM Gateway (no quota service for CLI - that's done at API level)
    try:
        gateway = LLMGateway(config, logging_service=logging_service, quota_service=None)
    except LLMGatewayError as e:
        logger.error(f"Failed to initialize LLM Gateway: {e}")
        sys.exit(1)

    if args.email_id:
        process_single_email(supabase_client, gateway, user_id, args.email_id)
    elif args.recent:
        process_recent_emails(supabase_client, gateway, user_id, args.recent)

    logger.info("\nDone!")


if __name__ == "__main__":
    main()
