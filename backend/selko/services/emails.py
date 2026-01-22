"""Email service for Selko.

Handles email parsing and database storage.
"""

from datetime import datetime
from typing import Any

from supabase import Client

from selko.services.auth import get_current_user_id


class EmailError(Exception):
    """Raised when email operations fail."""

    pass


def parse_gmail_message(email: dict[str, Any]) -> dict[str, Any]:
    """Parse Gmail API email into database format.

    Args:
        email: Full Gmail message object from API.

    Returns:
        Dict ready for database insertion.
    """
    headers = {
        h["name"].lower(): h["value"]
        for h in email.get("payload", {}).get("headers", [])
    }

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


def save_emails(
    client: Client,
    emails: list[dict[str, Any]],
) -> tuple[int, int]:
    """Save emails to Supabase database using upsert.

    The user_id is automatically determined from the authenticated session.

    Args:
        client: Authenticated Supabase client.
        emails: List of parsed email dicts (from parse_gmail_message).

    Returns:
        Tuple of (inserted_count, updated_count).

    Raises:
        EmailError: If save fails.
    """
    user_id = get_current_user_id(client)
    inserted = 0
    updated = 0

    for parsed in emails:
        # Add user_id to the email record
        parsed["user_id"] = user_id

        try:
            # Check if email already exists
            existing = (
                client.table("emails")
                .select("id")
                .eq("user_id", user_id)
                .eq("gmail_id", parsed["gmail_id"])
                .maybe_single()
                .execute()
            )

            if existing.data:
                # Update existing record
                client.table("emails").update(parsed).eq(
                    "id", existing.data["id"]
                ).execute()
                updated += 1
                subject = parsed.get("subject", "(no subject)")
                print(f"Updated: {subject[:50]}...")
            else:
                # Insert new record
                client.table("emails").insert(parsed).execute()
                inserted += 1
                subject = parsed.get("subject", "(no subject)")
                print(f"Inserted: {subject[:50]}...")

        except Exception as e:
            raise EmailError(f"Failed to save email: {e}") from e

    return inserted, updated
