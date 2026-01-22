#!/usr/bin/env python3
"""Gmail email fetching script.

Fetches recent emails from Gmail and saves them as JSON files.
"""

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

SCRIPT_DIR = Path(__file__).parent
CREDENTIALS_FILE = SCRIPT_DIR / "credentials.json"
TOKEN_FILE = SCRIPT_DIR / "token.json"
EMAILS_DIR = SCRIPT_DIR / "emails"


def get_credentials():
    """Load and refresh credentials from token.json."""
    if not TOKEN_FILE.exists():
        print(f"Error: {TOKEN_FILE} not found.")
        print("Run 'uv run python poc/auth_gmail.py' first to authenticate.")
        return None

    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds.expired and creds.refresh_token:
        print("Token expired, refreshing...")
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
        print("Token refreshed and saved.")

    return creds


def fetch_emails(service, max_results=10):
    """Fetch recent emails from inbox."""
    results = service.users().messages().list(
        userId="me", labelIds=["INBOX"], maxResults=max_results
    ).execute()

    messages = results.get("messages", [])
    if not messages:
        print("No messages found in inbox.")
        return []

    emails = []
    for msg in messages:
        full_msg = service.users().messages().get(
            userId="me", id=msg["id"], format="full"
        ).execute()
        emails.append(full_msg)

    return emails


def save_emails(emails):
    """Save emails to JSON files."""
    EMAILS_DIR.mkdir(exist_ok=True)

    for email in emails:
        email_id = email["id"]
        filepath = EMAILS_DIR / f"{email_id}.json"
        filepath.write_text(json.dumps(email, indent=2))
        print(f"Saved: {filepath.name}")


def main():
    creds = get_credentials()
    if not creds:
        return

    service = build("gmail", "v1", credentials=creds)

    print("Fetching 10 most recent emails from inbox...")
    emails = fetch_emails(service, max_results=10)

    if emails:
        save_emails(emails)
        print(f"\nDone! Saved {len(emails)} emails to {EMAILS_DIR}/")


if __name__ == "__main__":
    main()
