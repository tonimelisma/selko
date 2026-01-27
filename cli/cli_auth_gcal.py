#!/usr/bin/env python3
"""CLI for Google Calendar OAuth authentication.

Runs OAuth flow and stores tokens in the integrations table.
"""

import argparse
import logging
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from selko.config import add_logging_arguments, load_config
from selko.logging import setup_logging
from selko.services.auth import AuthenticationError, get_authenticated_client, get_current_user_id
from selko.services.integrations import CALENDAR_SCOPES, IntegrationError, save_oauth_credentials

logger = logging.getLogger(__name__)


class CalendarOAuthError(Exception):
    """Raised when Calendar OAuth flow fails."""

    pass


def run_calendar_oauth_flow(config) -> "Credentials":
    """Run OAuth flow for Google Calendar access.

    Opens a browser window for the user to authenticate.

    Args:
        config: Configuration with credentials file path.

    Returns:
        Google Credentials object with tokens.

    Raises:
        CalendarOAuthError: If credentials file not found or flow fails.
    """
    if not config.credentials_file.exists():
        raise CalendarOAuthError(
            f"Credentials file not found: {config.credentials_file}\n"
            "Download OAuth client credentials from Google Cloud Console "
            "and save as 'credentials.json' in the cli/ directory."
        )

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(config.credentials_file), CALENDAR_SCOPES
        )

        logger.info("Opening browser for Google Calendar authentication...")
        logger.info("If browser doesn't open, visit the URL shown below.")

        creds = flow.run_local_server(port=0)
        logger.info("OAuth flow completed successfully")
        return creds

    except FileNotFoundError as e:
        raise CalendarOAuthError(f"Credentials file not found: {e}") from e
    except ValueError as e:
        raise CalendarOAuthError(f"Invalid credentials file format: {e}") from e


def main():
    parser = argparse.ArgumentParser(
        description="Authenticate with Google Calendar and store tokens in database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run Google Calendar OAuth flow
  uv run python -m cli.cli_auth_gcal

  # Use staging environment
  ENVIRONMENT=staging uv run python -m cli.cli_auth_gcal

  # Enable verbose logging
  uv run python -m cli.cli_auth_gcal -v

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
        creds = run_calendar_oauth_flow(config)
    except CalendarOAuthError as e:
        logger.error(f"OAuth flow failed: {e}")
        sys.exit(1)

    # Save tokens to database
    # Note: Unlike Gmail, Calendar API doesn't have a profile endpoint
    # so we don't store provider_email
    try:
        user_id = get_current_user_id(client)
        save_oauth_credentials(client, user_id, "google_calendar", creds, None)
        logger.info("Google Calendar integration saved successfully!")
    except IntegrationError as e:
        logger.error(f"Error saving integration: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
