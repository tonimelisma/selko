#!/usr/bin/env python3
"""CLI for Gmail OAuth authentication.

Runs OAuth flow and stores tokens in the integrations table.
No more local token.json file.
"""

import argparse
import logging
import sys

from selko.config import add_logging_arguments, load_config
from selko.logging import setup_logging
from selko.services.auth import AuthenticationError, get_authenticated_client
from selko.services.gmail import GmailError, build_service, get_user_profile, run_oauth_flow
from selko.services.integrations import IntegrationError, save_oauth_credentials

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Authenticate with Gmail and store tokens in database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run Gmail OAuth flow
  uv run python -m cli.cli_auth_gmail

  # Use staging environment
  ENVIRONMENT=staging uv run python -m cli.cli_auth_gmail

  # Enable verbose logging
  uv run python -m cli.cli_auth_gmail -v

Note:
  Requires TEST_USER_EMAIL and TEST_USER_PASSWORD in .env
  Tokens are stored in the integrations table, not local files.
        """,
    )
    add_logging_arguments(parser)
    args = parser.parse_args()

    setup_logging(verbose=args.verbose, quiet=args.quiet)
    config = load_config()

    # Sign in as the test user
    try:
        client = get_authenticated_client(config)
    except AuthenticationError as e:
        logger.error(f"Authentication failed: {e}")
        sys.exit(1)

    # Run OAuth flow
    try:
        creds = run_oauth_flow(config)
    except GmailError as e:
        logger.error(f"OAuth flow failed: {e}")
        sys.exit(1)

    # Get Gmail profile to store provider email
    try:
        service = build_service(creds)
        profile = get_user_profile(service)
        gmail_address = profile.get("emailAddress")
    except Exception as e:
        logger.warning(f"Could not get Gmail profile: {e}")
        gmail_address = None

    # Save tokens to database
    try:
        save_oauth_credentials(client, "gmail", creds, gmail_address)
        logger.info("Gmail integration saved successfully!")
        if gmail_address:
            logger.info(f"Connected account: {gmail_address}")
    except IntegrationError as e:
        logger.error(f"Error saving integration: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
