#!/usr/bin/env python3
"""CLI for fetching Gmail emails.

Fetches emails from Gmail and stores them in Supabase.
No more local JSON file storage.
"""

import argparse
import sys

from selko.config import add_env_argument, load_config
from selko.services.auth import AuthenticationError, get_authenticated_client
from selko.services.emails import EmailError, parse_gmail_message, save_emails
from selko.services.gmail import (
    GmailError,
    build_service,
    fetch_messages,
    get_credentials,
)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Gmail emails and store in Supabase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fetch 10 most recent emails
  uv run python -m cli.cli_fetch_emails

  # Fetch 50 emails
  uv run python -m cli.cli_fetch_emails --max 50

  # Use staging environment
  uv run python -m cli.cli_fetch_emails --env staging

Note:
  Requires TEST_USER_EMAIL and TEST_USER_PASSWORD in .env
  Run cli_auth_gmail first to authenticate with Gmail.
        """,
    )
    add_env_argument(parser)
    parser.add_argument(
        "--max",
        type=int,
        default=10,
        help="Maximum number of emails to fetch (default: 10)",
    )
    args = parser.parse_args()

    config = load_config(args.env)

    # Sign in as the test user
    try:
        client = get_authenticated_client(config)
    except AuthenticationError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Get Gmail credentials from database
    try:
        creds = get_credentials(client, config)
        if not creds:
            print("No Gmail integration found.")
            print("Run 'uv run python -m cli.cli_auth_gmail' first to authenticate.")
            sys.exit(1)
    except Exception as e:
        print(f"Error getting credentials: {e}")
        sys.exit(1)

    # Build Gmail service and fetch emails
    try:
        service = build_service(creds)
        print(f"Fetching {args.max} most recent emails from inbox...")
        messages = fetch_messages(service, max_results=args.max)
    except GmailError as e:
        print(f"Error fetching emails: {e}")
        sys.exit(1)

    if not messages:
        print("No emails found.")
        return

    # Parse and save emails
    try:
        parsed = [parse_gmail_message(msg) for msg in messages]
        inserted, updated = save_emails(client, parsed)
        print(f"\nDone! Inserted: {inserted}, Updated: {updated}")
    except EmailError as e:
        print(f"Error saving emails: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
