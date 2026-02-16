#!/usr/bin/env python3
"""CLI for extracting calendar events from emails using LLM.

Analyzes email content and attachments to extract structured calendar events.
Preview-only — does not save events to the database.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from selko.config import add_logging_arguments, load_config
from selko.logging import setup_logging
from selko.services.auth import AuthenticationError, get_authenticated_client
from selko.services.event_processing import (
    extract_calendar_events,
    fetch_email_with_attachments,
)
from selko.services.llm_gateway import LLMGateway, LLMGatewayError
from selko.services.llm_provider import create_provider

logger = logging.getLogger(__name__)


def load_fixture(fixture_path: Path) -> dict:
    """Load a test fixture JSON file.

    Args:
        fixture_path: Path to fixture file.

    Returns:
        Parsed fixture data.
    """
    with open(fixture_path) as f:
        return json.load(f)


def extract_from_fixture(gateway, fixture_path: Path, output_json: bool = False):
    """Extract events from a test fixture file.

    Args:
        gateway: LLMGateway instance.
        fixture_path: Path to fixture JSON file.
        output_json: If True, output raw JSON instead of formatted text.
    """
    logger.info(f"Loading fixture: {fixture_path}")
    fixture = load_fixture(fixture_path)

    input_data = fixture["input"]
    email_metadata = {
        "gmail_id": input_data["gmail_id"],
        "subject": input_data["subject"],
        "from_name": input_data.get("from_name"),
        "from_email": input_data["from_email"],
        "date_sent": input_data["date_sent"],
    }

    logger.info(f"Extracting events from: {input_data['subject']}")

    try:
        result = extract_calendar_events(
            gateway=gateway,
            email_text=input_data["body_text"],
            email_metadata=email_metadata,
            attachments=input_data.get("attachments", []),
        )

        if output_json:
            print(result.model_dump_json(indent=2))
        else:
            print_extraction_result(result)

    except LLMGatewayError as e:
        logger.error(f"Extraction failed: {e}")
        sys.exit(1)


def extract_from_database(
    gateway, supabase_client, email_id: str, output_json: bool = False
):
    """Extract events from an email in the database.

    Args:
        gateway: LLMGateway instance.
        supabase_client: Authenticated Supabase client.
        email_id: UUID of email record.
        output_json: If True, output raw JSON instead of formatted text.
    """
    logger.info(f"Fetching email from database: {email_id}")

    try:
        email_metadata, email_text, attachments = fetch_email_with_attachments(
            supabase_client, email_id
        )

        logger.info(f"Extracting events from: {email_metadata.get('subject', '(no subject)')}")

        result = extract_calendar_events(
            gateway=gateway,
            email_text=email_text,
            email_metadata=email_metadata,
            attachments=attachments,
        )

        if output_json:
            print(result.model_dump_json(indent=2))
        else:
            print_extraction_result(result)

    except LLMGatewayError as e:
        logger.error(f"Extraction failed: {e}")
        sys.exit(1)


def extract_from_recent(
    gateway, supabase_client, max_emails: int, output_json: bool = False
):
    """Extract events from recent emails in the database.

    Args:
        gateway: LLMGateway instance.
        supabase_client: Authenticated Supabase client.
        max_emails: Maximum number of emails to process.
        output_json: If True, output raw JSON instead of formatted text.
    """
    logger.info(f"Fetching {max_emails} most recent emails...")

    try:
        # Fetch recent emails
        result = (
            supabase_client.table("emails")
            .select("id, subject, from_email, date_sent")
            .order("date_sent", desc=True)
            .limit(max_emails)
            .execute()
        )

        if not result.data:
            logger.info("No emails found")
            return

        logger.info(f"Processing {len(result.data)} emails...")

        total_events = 0
        for email_record in result.data:
            email_id = email_record["id"]
            subject = email_record.get("subject", "(no subject)")

            logger.info(f"\n{'='*60}")
            logger.info(f"Email: {subject[:50]}...")

            try:
                email_metadata, email_text, attachments = fetch_email_with_attachments(
                    supabase_client, email_id
                )

                extraction_result = extract_calendar_events(
                    gateway=gateway,
                    email_text=email_text,
                    email_metadata=email_metadata,
                    attachments=attachments,
                )

                if output_json:
                    print(extraction_result.model_dump_json(indent=2))
                else:
                    print_extraction_result(extraction_result, compact=True)

                total_events += len(extraction_result.events)

            except LLMGatewayError as e:
                logger.error(f"Failed to process email {email_id}: {e}")
                continue

        logger.info(f"\n{'='*60}")
        logger.info(f"Total events extracted: {total_events}")

    except Exception as e:
        logger.error(f"Failed to fetch emails: {e}")
        sys.exit(1)


def print_extraction_result(result, compact: bool = False):
    """Pretty-print extraction results.

    Args:
        result: CalendarEventExtraction instance.
        compact: If True, use compact format for batch processing.
    """
    if not compact:
        print("\n" + "=" * 60)
        print("EXTRACTION RESULT")
        print("=" * 60)
        print(f"Email: {result.email_message_id}")
        print(f"From: {result.sender_name or ''} <{result.sender_email}>")
        print(f"Date: {result.email_date}")
        print(f"\nEvents Found: {result.events_found}")
        print(f"Event Count: {len(result.events)}")

    if result.events_found and result.events:
        if not compact:
            print("\n" + "-" * 60)
            print("EXTRACTED EVENTS")
            print("-" * 60)

        for i, event in enumerate(result.events, 1):
            if compact:
                print(f"\n  Event {i}: {event.title}")
            else:
                print(f"\nEvent {i}:")
                print(f"  Title: {event.title}")

            if event.start_datetime:
                print(f"  Start: {event.start_datetime}")
            if event.end_datetime:
                print(f"  End: {event.end_datetime}")
            if event.location:
                print(f"  Location: {event.location}")

            if not compact:
                print(f"  Description: {event.description}")
                print(f"  Confidence: {event.confidence:.2f}")
    else:
        if not compact:
            print("\nNo calendar events found in this email.")

    if not compact:
        print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Extract calendar events from emails using LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract from database email by ID
  uv run python -m cli.cli_extract_events --email-id <uuid>

  # Extract from recent emails
  uv run python -m cli.cli_extract_events --recent 5

  # Extract from test fixture
  uv run python -m cli.cli_extract_events --fixture event_birthday_party.json

  # Output as JSON
  uv run python -m cli.cli_extract_events --email-id <uuid> --json

  # Use different environment
  ENVIRONMENT=staging uv run python -m cli.cli_extract_events --recent 10

Note:
  Requires GEMINI_API_KEY (or other LLM provider key) in .env file.
  For database operations, requires TEST_USER_EMAIL and TEST_USER_PASSWORD.
        """,
    )

    add_logging_arguments(parser)

    # Mutually exclusive source options
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--email-id",
        type=str,
        help="UUID of email in database to analyze",
    )
    source_group.add_argument(
        "--recent",
        type=int,
        metavar="N",
        help="Extract from N most recent emails in database",
    )
    source_group.add_argument(
        "--fixture",
        type=str,
        help="Path to test fixture JSON file",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of formatted text",
    )

    args = parser.parse_args()

    setup_logging(verbose=args.verbose, quiet=args.quiet)
    config = load_config()

    # Initialize LLM Gateway
    try:
        provider = create_provider(config)
        gateway = LLMGateway(provider)
    except LLMGatewayError as e:
        logger.error(f"Failed to initialize LLM Gateway: {e}")
        sys.exit(1)

    # Handle fixture mode (no Supabase needed)
    if args.fixture:
        fixture_path = Path(args.fixture)
        if not fixture_path.is_absolute():
            # Check in fixtures directory
            fixtures_dir = (
                Path(__file__).parent.parent
                / "backend"
                / "tests"
                / "fixtures"
                / "emails"
            )
            fixture_path = fixtures_dir / args.fixture

        if not fixture_path.exists():
            logger.error(f"Fixture file not found: {fixture_path}")
            sys.exit(1)

        extract_from_fixture(gateway, fixture_path, args.json)
        return

    # Handle database modes (require Supabase authentication)
    try:
        supabase_client = get_authenticated_client(config)
    except AuthenticationError as e:
        logger.error(f"Authentication failed: {e}")
        sys.exit(1)

    if args.email_id:
        extract_from_database(gateway, supabase_client, args.email_id, args.json)
    elif args.recent:
        extract_from_recent(gateway, supabase_client, args.recent, args.json)


if __name__ == "__main__":
    main()
