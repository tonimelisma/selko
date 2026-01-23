"""Email service for Selko.

Handles email parsing and database storage.
"""

import logging
from datetime import datetime
from email.utils import getaddresses, parseaddr
from typing import Any

from supabase import Client, PostgrestAPIError

from selko.services.auth import get_current_user_id

logger = logging.getLogger(__name__)


class EmailError(Exception):
    """Raised when email operations fail."""

    pass


def parse_gmail_message(email: dict[str, Any]) -> dict[str, Any]:
    """Parse Gmail API email into database format.

    Uses Python stdlib email.utils for RFC 5322 compliant header parsing.

    Args:
        email: Full Gmail message object from API.

    Returns:
        Dict ready for database insertion.
    """
    headers = {
        h["name"].lower(): h["value"]
        for h in email.get("payload", {}).get("headers", [])
    }

    # Use stdlib for reliable RFC 5322 parsing
    from_header = headers.get("from", "")
    from_name, from_email = parseaddr(from_header)

    # Handle multiple recipients using stdlib
    to_header = headers.get("to", "")
    to_addresses = getaddresses([to_header])
    to_emails = [addr[1] for addr in to_addresses if addr[1]]

    # Parse date
    date_sent = None
    date_header = headers.get("date")
    if date_header:
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

    # Check for attachments
    has_attachments = any(
        part.get("filename")
        for part in email.get("payload", {}).get("parts", [])
    )

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
        "has_attachments": has_attachments,
    }


def _log_email_subject(parsed: dict[str, Any], action: str) -> None:
    """Log email subject for debugging."""
    subject = parsed.get("subject", "(no subject)")
    if len(subject) > 50:
        subject = subject[:50] + "..."
    logger.debug(f"{action}: {subject}")


def save_emails(
    client: Client,
    emails: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Save emails to Supabase database using upsert.

    The user_id is automatically determined from the authenticated session.
    Uses single upsert operation for efficiency.

    Args:
        client: Authenticated Supabase client.
        emails: List of parsed email dicts (from parse_gmail_message).

    Returns:
        List of saved email records (with database IDs).

    Raises:
        EmailError: If save fails.
    """
    user_id = get_current_user_id(client)
    saved_records = []

    for parsed in emails:
        # Add user_id to the email record
        parsed["user_id"] = user_id

        try:
            # Single upsert instead of SELECT + INSERT/UPDATE
            result = client.table("emails").upsert(
                parsed, on_conflict="user_id,gmail_id"
            ).execute()
            if result.data:
                saved_records.append(result.data[0])
            _log_email_subject(parsed, "Saved")

        except PostgrestAPIError as e:
            raise EmailError(f"Failed to save email: {e.message}") from e

    logger.info(f"Saved {len(saved_records)} emails")
    return saved_records
