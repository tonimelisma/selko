#!/usr/bin/env python3
"""Gmail email fetching script.

Fetches recent emails from Gmail and stores them in Supabase database.
Optionally saves raw JSON files for debugging.
"""

import argparse
import json
from datetime import datetime
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from supabase import Client

from poc.config import Config, add_env_argument, get_supabase_client, load_config

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_credentials(config: Config) -> Optional[Credentials]:
    """Load and refresh credentials from token.json."""
    if not config.token_file.exists():
        print(f"Error: {config.token_file} not found.")
        print("Run 'uv run python poc/auth_gmail.py' first to authenticate.")
        return None

    creds = Credentials.from_authorized_user_file(str(config.token_file), SCOPES)

    if creds.expired and creds.refresh_token:
        print("Token expired, refreshing...")
        creds.refresh(Request())
        config.token_file.write_text(creds.to_json())
        print("Token refreshed and saved.")

    return creds


def fetch_emails_from_gmail(service, max_results: int = 10) -> list[dict]:
    """Fetch recent emails from inbox."""
    results = (
        service.users()
        .messages()
        .list(userId="me", labelIds=["INBOX"], maxResults=max_results)
        .execute()
    )

    messages = results.get("messages", [])
    if not messages:
        print("No messages found in inbox.")
        return []

    emails = []
    for msg in messages:
        full_msg = (
            service.users().messages().get(userId="me", id=msg["id"], format="full")
        ).execute()
        emails.append(full_msg)

    return emails


def parse_email_headers(email: dict[str, Any]) -> dict[str, Any]:
    """Parse Gmail API email into database format."""
    headers = {h["name"].lower(): h["value"] for h in email.get("payload", {}).get("headers", [])}

    # Parse from header (format: "Name <email>" or just "email")
    from_header = headers.get("from", "")
    from_name = None
    from_email = from_header

    if "<" in from_header and ">" in from_header:
        parts = from_header.split("<")
        from_name = parts[0].strip().strip('"')
        from_email = parts[1].rstrip(">").strip()

    # Parse to header (comma-separated list)
    to_header = headers.get("to", "")
    to_emails = [addr.strip() for addr in to_header.split(",") if addr.strip()]

    # Parse date
    date_sent = None
    date_header = headers.get("date")
    if date_header:
        try:
            # Gmail date format varies, try common formats
            for fmt in [
                "%a, %d %b %Y %H:%M:%S %z",
                "%d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S %Z",
            ]:
                try:
                    date_sent = datetime.strptime(date_header, fmt).isoformat()
                    break
                except ValueError:
                    continue
        except Exception:
            pass

    return {
        "gmail_id": email["id"],
        "thread_id": email.get("threadId"),
        "subject": headers.get("subject"),
        "from_email": from_email,
        "from_name": from_name if from_name else None,
        "to_emails": to_emails if to_emails else None,
        "date_sent": date_sent,
        "snippet": email.get("snippet"),
        "gmail_label_ids": email.get("labelIds", []),
        "has_attachments": any(
            part.get("filename") for part in email.get("payload", {}).get("parts", [])
        ),
    }


def save_emails_to_json(emails: list[dict], config: Config) -> None:
    """Save emails to JSON files for debugging."""
    config.emails_dir.mkdir(exist_ok=True)

    for email in emails:
        email_id = email["id"]
        filepath = config.emails_dir / f"{email_id}.json"
        filepath.write_text(json.dumps(email, indent=2))
        print(f"Saved JSON: {filepath.name}")


def save_emails_to_supabase(
    emails: list[dict], supabase: Client, user_id: str
) -> tuple[int, int]:
    """Save emails to Supabase database using upsert.

    Returns:
        Tuple of (inserted_count, updated_count).
    """
    inserted = 0
    updated = 0

    for email in emails:
        parsed = parse_email_headers(email)
        parsed["user_id"] = user_id

        # Check if email already exists
        existing = (
            supabase.table("emails")
            .select("id")
            .eq("user_id", user_id)
            .eq("gmail_id", parsed["gmail_id"])
            .execute()
        )

        if existing.data:
            # Update existing record
            supabase.table("emails").update(parsed).eq(
                "id", existing.data[0]["id"]
            ).execute()
            updated += 1
            print(f"Updated: {parsed['subject'][:50] if parsed['subject'] else '(no subject)'}...")
        else:
            # Insert new record
            supabase.table("emails").insert(parsed).execute()
            inserted += 1
            print(f"Inserted: {parsed['subject'][:50] if parsed['subject'] else '(no subject)'}...")

    return inserted, updated


def main(config: Config, save_json: bool = False, user_id: Optional[str] = None) -> None:
    """Fetch emails and store in Supabase."""
    creds = get_gmail_credentials(config)
    if not creds:
        return

    service = build("gmail", "v1", credentials=creds)

    print("Fetching 10 most recent emails from inbox...")
    emails = fetch_emails_from_gmail(service, max_results=10)

    if not emails:
        return

    # Save to JSON files if requested
    if save_json:
        save_emails_to_json(emails, config)

    # Save to Supabase
    if not user_id:
        print("\nWarning: No user_id provided, skipping database storage.")
        print("Use --user-id to specify the user ID for database storage.")
        return

    print(f"\nStoring {len(emails)} emails in Supabase ({config.environment})...")
    supabase = get_supabase_client(config, use_service_role=True)

    try:
        inserted, updated = save_emails_to_supabase(emails, supabase, user_id)
        print(f"\nDone! Inserted: {inserted}, Updated: {updated}")
    except Exception as e:
        print(f"\nError storing emails: {e}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch Gmail emails and store in Supabase"
    )
    add_env_argument(parser)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Also save raw email JSON files for debugging",
    )
    parser.add_argument(
        "--user-id",
        help="User ID (UUID) for database storage",
    )
    args = parser.parse_args()

    cfg = load_config(args.env)
    main(cfg, save_json=args.json, user_id=args.user_id)
