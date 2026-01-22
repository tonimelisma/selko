#!/usr/bin/env python3
"""Gmail OAuth authentication script.

Authenticates with Gmail API using OAuth 2.0 and saves tokens for later use.
"""

import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

SCRIPT_DIR = Path(__file__).parent
CREDENTIALS_FILE = SCRIPT_DIR / "credentials.json"
TOKEN_FILE = SCRIPT_DIR / "token.json"


def main():
    if not CREDENTIALS_FILE.exists():
        print(f"Error: {CREDENTIALS_FILE} not found.")
        print("Download OAuth client credentials from Google Cloud Console")
        print("and save as 'credentials.json' in the poc/ directory.")
        return

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)

    print("Opening browser for authentication...")
    print("If browser doesn't open, visit the URL shown below.\n")

    creds = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(creds.to_json())
    print(f"\nAuthentication successful! Token saved to {TOKEN_FILE}")


if __name__ == "__main__":
    main()
