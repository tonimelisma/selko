#!/usr/bin/env python3
"""Gmail OAuth authentication script.

Authenticates with Gmail API using OAuth 2.0 and saves tokens for later use.
"""

import argparse

from google_auth_oauthlib.flow import InstalledAppFlow

from poc.config import Config, add_env_argument, load_config

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main(config: Config) -> None:
    """Run OAuth flow and save credentials."""
    if not config.credentials_file.exists():
        print(f"Error: {config.credentials_file} not found.")
        print("Download OAuth client credentials from Google Cloud Console")
        print("and save as 'credentials.json' in the poc/ directory.")
        return

    flow = InstalledAppFlow.from_client_secrets_file(
        str(config.credentials_file), SCOPES
    )

    print("Opening browser for authentication...")
    print("If browser doesn't open, visit the URL shown below.\n")

    creds = flow.run_local_server(port=0)

    config.token_file.write_text(creds.to_json())
    print(f"\nAuthentication successful! Token saved to {config.token_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Authenticate with Gmail API using OAuth 2.0"
    )
    add_env_argument(parser)
    args = parser.parse_args()

    cfg = load_config(args.env)
    main(cfg)
