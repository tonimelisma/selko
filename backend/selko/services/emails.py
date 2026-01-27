"""Email service for Selko.

Handles email parsing and database storage.
"""

import logging
from datetime import datetime
from email.utils import getaddresses, parseaddr
from typing import Any, Optional

from supabase import Client, PostgrestAPIError

from selko.config import Config
from selko.services.auth import get_current_user_id
from selko.services.gmail import (
    GmailError,
    build_service,
    extract_attachments,
    fetch_messages,
    get_credentials,
)
from selko.services.attachments import AttachmentError, process_attachment

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
    user_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Save emails to Supabase database using upsert.

    The user_id can be provided explicitly (for service role operations)
    or determined from the authenticated session.

    Args:
        client: Authenticated Supabase client.
        emails: List of parsed email dicts (from parse_gmail_message).
        user_id: Optional user ID (required if using service role client).

    Returns:
        List of saved email records (with database IDs).

    Raises:
        EmailError: If save fails.
    """
    if user_id is None:
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


def fetch_emails_for_user(
    client: Client,
    config: Config,
    max_results: int = 10,
    fetch_attachments: bool = True,
) -> dict[str, int]:
    """Fetch emails from Gmail and store in Supabase.

    Adapts the logic from cli_fetch_emails.py for API usage.

    Args:
        client: Authenticated Supabase client (user session).
        config: Configuration object with Google OAuth credentials.
        max_results: Maximum number of emails to fetch.
        fetch_attachments: Whether to download and store attachments.

    Returns:
        Dict with counts: {fetched, saved, attachments_downloaded}.

    Raises:
        EmailError: If fetching or saving fails.
    """
    # Get Gmail credentials from database
    try:
        creds = get_credentials(client, config)
        if not creds:
            raise EmailError("No Gmail integration found. Please authenticate with Gmail first.")
    except Exception as e:
        raise EmailError(f"Error getting credentials: {e}") from e

    # Build Gmail service and fetch emails
    try:
        service = build_service(creds)
        logger.info(f"Fetching {max_results} most recent emails from inbox...")
        messages = fetch_messages(service, max_results=max_results)
    except GmailError as e:
        raise EmailError(f"Error fetching emails: {e}") from e

    if not messages:
        logger.info("No emails found")
        return {"fetched": 0, "saved": 0, "attachments_downloaded": 0}

    # Parse and save emails
    try:
        parsed = [parse_gmail_message(msg) for msg in messages]
        saved_records = save_emails(client, parsed)
        logger.info(f"Saved {len(saved_records)} emails")
    except EmailError as e:
        raise EmailError(f"Error saving emails: {e}") from e

    attachments_downloaded = 0

    # Process attachments if requested
    if fetch_attachments:
        logger.info("Fetching attachments for saved emails...")

        # Map gmail_id to saved record for lookup
        gmail_id_to_record = {r["gmail_id"]: r for r in saved_records}

        for msg in messages:
            gmail_id = msg["id"]
            email_record = gmail_id_to_record.get(gmail_id)

            if not email_record:
                logger.warning(f"No saved record for message {gmail_id}")
                continue

            attachments = extract_attachments(msg)
            if not attachments:
                continue

            logger.info(
                f"Processing {len(attachments)} attachments for: "
                f"{email_record.get('subject', '(no subject)')[:50]}"
            )

            for att_part in attachments:
                try:
                    result = process_attachment(
                        client=client,
                        gmail_service=service,
                        email_id=email_record["id"],
                        message_id=gmail_id,
                        attachment_part=att_part,
                        config=config,
                    )
                    if result:
                        attachments_downloaded += 1
                except AttachmentError as e:
                    logger.error(f"Failed to process attachment: {e}")
                    continue

        logger.info(f"Downloaded {attachments_downloaded} attachments")

    return {
        "fetched": len(messages),
        "saved": len(saved_records),
        "attachments_downloaded": attachments_downloaded,
    }
