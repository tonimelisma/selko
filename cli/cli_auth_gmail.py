#!/usr/bin/env python3
"""CLI for Gmail OAuth authentication.

Runs OAuth flow and stores tokens in the integrations table.
No more local token.json file.
"""

import argparse
import sys

from selko.config import add_env_argument, load_config
from selko.services.auth import AuthenticationError, get_authenticated_client
from selko.services.gmail import GmailError, build_service, get_user_profile, run_oauth_flow
from selko.services.integrations import IntegrationError, save_oauth_credentials


def main():
    parser = argparse.ArgumentParser(
        description="Authenticate with Gmail and store tokens in database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run Gmail OAuth flow
  uv run python -m cli.cli_auth_gmail

  # Use staging environment
  uv run python -m cli.cli_auth_gmail --env staging

Note:
  Requires TEST_USER_EMAIL and TEST_USER_PASSWORD in .env
  Tokens are stored in the integrations table, not local files.
        """,
    )
    add_env_argument(parser)
    args = parser.parse_args()

    config = load_config(args.env)

    # Sign in as the test user
    try:
        client = get_authenticated_client(config)
    except AuthenticationError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Run OAuth flow
    try:
        creds = run_oauth_flow(config)
    except GmailError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Get Gmail profile to store provider email
    try:
        service = build_service(creds)
        profile = get_user_profile(service)
        gmail_address = profile.get("emailAddress")
    except Exception as e:
        print(f"Warning: Could not get Gmail profile: {e}")
        gmail_address = None

    # Save tokens to database
    try:
        save_oauth_credentials(client, "gmail", creds, gmail_address)
        print(f"\nGmail integration saved successfully!")
        if gmail_address:
            print(f"Connected account: {gmail_address}")
    except IntegrationError as e:
        print(f"Error saving integration: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
