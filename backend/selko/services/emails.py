"""Email service for Selko.

Handles email parsing and database storage.
"""

import base64
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from typing import Any, Optional

from supabase import Client, PostgrestAPIError

from selko.config import Config
from selko.services.auth import get_current_user_id
from selko.services.gmail import (
    GmailError,
    build_service,
    extract_attachments,
    extract_inline_images,
    fetch_messages,
    get_credentials,
)
from selko.services.attachments import AttachmentError, process_attachment, store_image_content
from selko.services.retry_utils import calculate_retry_delay
from selko.services.email_images import extract_data_uri_images, extract_linked_images
from selko.services.ics_parser import INVITE_METHODS

logger = logging.getLogger(__name__)


def _parse_email_date(date_header: Optional[str], internal_date_ms: Any) -> Optional[str]:
    """Parse email sent time from RFC 5322 Date header or Gmail internalDate.

    Returns ISO-8601 string for DB storage, or None if neither source works.
    """
    if date_header:
        try:
            return parsedate_to_datetime(date_header).isoformat()
        except (TypeError, ValueError, IndexError) as e:
            logger.warning(f"Failed to parse Date header '{date_header}': {e}")

    # Gmail always provides internalDate (epoch ms) even when Date is missing
    if internal_date_ms is not None and str(internal_date_ms).strip() != "":
        try:
            ms = int(internal_date_ms)
            return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError) as e:
            logger.warning(f"Failed to parse internalDate '{internal_date_ms}': {e}")

    return None


class EmailError(Exception):
    """Raised when email operations fail."""

    pass


class NoGmailIntegrationError(EmailError):
    """Raised when no Gmail integration is found for the user."""

    pass


class ExpiredCredentialsError(EmailError):
    """Raised when Gmail credentials are expired or revoked."""

    pass


def _extract_body_from_payload(payload: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Extract plain text and HTML body from Gmail MIME payload.

    Recursively walks MIME parts to find text/plain and text/html bodies.

    Args:
        payload: Gmail message payload dict.

    Returns:
        Tuple of (body_text, body_html), either may be None.
    """
    body_text = None
    body_html = None

    def _extract_from_part(part: dict[str, Any]) -> None:
        nonlocal body_text, body_html
        mime_type = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")

        if data and mime_type == "text/plain" and body_text is None:
            try:
                body_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            except Exception:
                pass
        elif data and mime_type == "text/html" and body_html is None:
            try:
                body_html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            except Exception:
                pass

        # Recurse into nested parts
        for nested in part.get("parts", []):
            _extract_from_part(nested)

    _extract_from_part(payload)
    return body_text, body_html


_METHOD_HEADER_RE = re.compile(r"method\s*=\s*\"?([A-Za-z]+)\"?", re.IGNORECASE)
_METHOD_BODY_RE = re.compile(r"^METHOD:(\S+)", re.IGNORECASE | re.MULTILINE)


def _method_from_part_headers(headers: list[dict[str, Any]]) -> Optional[str]:
    """Resolve a MIME part's calendar METHOD from its Content-Type header."""
    for header in headers:
        if header.get("name", "").lower() == "content-type":
            match = _METHOD_HEADER_RE.search(header.get("value", ""))
            if match:
                return match.group(1).upper()
    return None


def _detect_gmail_invite_method(payload: dict[str, Any]) -> Optional[str]:
    """Walk Gmail MIME parts for a text/calendar part and resolve its METHOD.

    Real invite machinery (REQUEST/REPLY/CANCEL/...) is distinguished from a
    shareable "add to calendar" file (PUBLISH / no METHOD) by RFC 5545 METHOD.
    Resolved from the part's Content-Type header first, then from the inline
    body if base64url data is present. Attachment-only bodies (no inline
    data) are left undetermined — the process-time backstop covers those.
    """

    def _walk(part: dict[str, Any]) -> Optional[str]:
        if part.get("mimeType", "") == "text/calendar":
            method = _method_from_part_headers(part.get("headers", []))
            if method:
                return method
            data = part.get("body", {}).get("data")
            if data:
                try:
                    decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                except Exception:
                    return None
                match = _METHOD_BODY_RE.search(decoded)
                if match:
                    return match.group(1).strip().upper()
            return None
        for nested in part.get("parts", []):
            result = _walk(nested)
            if result:
                return result
        return None

    return _walk(payload)


def mark_parsed_as_calendar_invite(parsed: dict[str, Any]) -> None:
    """Set the skip fields so an ingest-detected invite never enters the queue.

    Mutates ``parsed`` in place. Only called when ``is_calendar_invite`` is
    true — must never be called unconditionally, since ``save_emails`` upserts
    these keys as-is and an absent key on a re-save (e.g. a folder move)
    leaves the existing value alone, while an explicit key would clobber it.
    """
    parsed["processing_status"] = "skipped"
    parsed["processing_outcome"] = "calendar_invite"
    parsed["processing_explanation"] = (
        "Calendar invitation — already handled by your email client and calendar."
    )
    parsed["processed_at"] = datetime.now(timezone.utc).isoformat()


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

    # Parse date — prefer RFC 5322 Date header; fall back to Gmail internalDate
    date_sent = _parse_email_date(headers.get("date"), email.get("internalDate"))

    # Check for attachments
    has_attachments = any(
        part.get("filename")
        for part in email.get("payload", {}).get("parts", [])
    )

    # Extract body text and HTML from MIME payload
    payload = email.get("payload", {})
    body_text, body_html = _extract_body_from_payload(payload)

    result = {
        "email_provider": "gmail",
        "provider_message_id": email["id"],
        "thread_id": email.get("threadId"),
        "subject": headers.get("subject"),
        "from_email": from_email,
        "from_name": from_name if from_name else None,
        "to_emails": to_emails if to_emails else None,
        "date_sent": date_sent,
        "snippet": email.get("snippet"),
        "provider_labels": email.get("labelIds", []),
        "has_attachments": has_attachments,
    }

    # Add body columns if content was found
    if body_text:
        result["body_text"] = body_text
    if body_html:
        result["body_html"] = body_html

    invite_method = _detect_gmail_invite_method(payload)
    result["is_calendar_invite"] = invite_method in INVITE_METHODS
    if result["is_calendar_invite"]:
        mark_parsed_as_calendar_invite(result)

    return result


def _log_email_subject(parsed: dict[str, Any], action: str) -> None:
    """Log email subject for debugging."""
    subject = parsed.get("subject") or "(no subject)"
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
                parsed, on_conflict="user_id,email_provider,provider_message_id"
            ).execute()
            if result.data:
                saved_records.append(result.data[0])
            _log_email_subject(parsed, "Saved")

        except PostgrestAPIError as e:
            raise EmailError(f"Failed to save email: {e.message}") from e

    logger.info(f"Saved {len(saved_records)} emails")
    return saved_records


def store_gmail_message_attachments(
    client: Client,
    config: Config,
    service: Any,
    message: dict[str, Any],
    email_record: dict[str, Any],
    parsed_email: dict[str, Any] | None = None,
    *,
    raise_on_error: bool = False,
) -> int:
    """Download attachments/images for an already-eligible Gmail message.

    Callers must invoke this only after the message's provider labels have been
    checked. Keeping the download helper separate makes it impossible for a
    rejected message to reach attachment storage in the reliable sync path.
    """

    message_id = message["id"]
    email_id = email_record["id"]
    images_stored = 0

    for attachment_part in extract_attachments(message):
        try:
            if process_attachment(
                client=client,
                gmail_service=service,
                email_id=email_id,
                message_id=message_id,
                attachment_part=attachment_part,
                config=config,
            ):
                images_stored += 1
        except AttachmentError as exc:
            if raise_on_error:
                raise
            logger.warning("Failed to process Gmail attachment for %s: %s", message_id, exc)

    for inline_part in extract_inline_images(message):
        try:
            if process_attachment(
                client=client,
                gmail_service=service,
                email_id=email_id,
                message_id=message_id,
                attachment_part=inline_part,
                config=config,
            ):
                images_stored += 1
        except AttachmentError as exc:
            if raise_on_error:
                raise
            logger.warning("Failed to process Gmail inline image for %s: %s", message_id, exc)

    body_html = (parsed_email or {}).get("body_html")
    if body_html:
        try:
            linked_images = extract_linked_images(body_html)
        except Exception as exc:
            logger.warning("Failed to extract linked Gmail images for %s: %s", message_id, exc)
            linked_images = []
        for idx, image in enumerate(linked_images):
            try:
                if store_image_content(
                    client=client,
                    email_id=email_id,
                    image_data=image.data,
                    mime_type=image.mime_type,
                    filename=f"linked_{idx}.{image.mime_type.split('/')[-1]}",
                    config=config,
                ):
                    images_stored += 1
            except AttachmentError as exc:
                if raise_on_error:
                    raise
                logger.warning("Failed to store linked Gmail image for %s: %s", message_id, exc)

        try:
            data_uri_images = extract_data_uri_images(body_html)
        except Exception as exc:
            logger.warning("Failed to extract data URI Gmail images for %s: %s", message_id, exc)
            data_uri_images = []
        for idx, image in enumerate(data_uri_images):
            try:
                if store_image_content(
                    client=client,
                    email_id=email_id,
                    image_data=image.data,
                    mime_type=image.mime_type,
                    filename=f"data_uri_{idx}.{image.mime_type.split('/')[-1]}",
                    config=config,
                ):
                    images_stored += 1
            except AttachmentError as exc:
                if raise_on_error:
                    raise
                logger.warning("Failed to store data URI Gmail image for %s: %s", message_id, exc)

    if images_stored and not email_record.get("has_attachments"):
        client.table("emails").update({"has_attachments": True}).eq(
            "id", email_id
        ).execute()
    return images_stored


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
            raise NoGmailIntegrationError("No Gmail integration found. Please authenticate with Gmail first.")
    except (NoGmailIntegrationError, ExpiredCredentialsError):
        raise
    except Exception as e:
        raise EmailError(f"Error getting credentials: {e}") from e

    # Manual and scheduled syncs share the same cursor-based implementation.
    # Keep this import local because the worker imports parsing/storage helpers
    # from this module.
    try:
        integration_result = (
            client.table("integrations")
            .select("id")
            .eq("provider", "gmail")
            .maybe_single()
            .execute()
        )
        if integration_result and integration_result.data and integration_result.data.get("id"):
            from selko.workers.email_fetch import _process_gmail_fetch_sync

            return _process_gmail_fetch_sync(
                client,
                config,
                {
                    "user_id": get_current_user_id(client),
                    "provider": "gmail",
                    "fetch_attachments": fetch_attachments,
                },
            )
    except EmailError:
        raise
    except Exception as e:
        raise EmailError(f"Error preparing reliable Gmail sync: {e}") from e

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

    # Process attachments and images if requested
    if fetch_attachments:
        logger.info("Fetching attachments and images for saved emails...")

        # Map provider message IDs to saved records and parsed data for lookup
        provider_message_id_to_record = {
            r["provider_message_id"]: r for r in saved_records
        }
        provider_message_id_to_parsed = {
            p["provider_message_id"]: p for p in parsed
        }

        for msg in messages:
            provider_message_id = msg["id"]
            email_record = provider_message_id_to_record.get(provider_message_id)

            if not email_record:
                logger.warning(f"No saved record for message {provider_message_id}")
                continue

            email_id = email_record["id"]
            images_stored = 0

            # 1. Regular file attachments (existing logic)
            attachments = extract_attachments(msg)
            if attachments:
                logger.info(
                    f"Processing {len(attachments)} attachments for: "
                    f"{email_record.get('subject', '(no subject)')[:50]}"
                )

                for att_part in attachments:
                    try:
                        result = process_attachment(
                            client=client,
                            gmail_service=service,
                            email_id=email_id,
                            message_id=provider_message_id,
                            attachment_part=att_part,
                            config=config,
                        )
                        if result:
                            attachments_downloaded += 1
                    except AttachmentError as e:
                        logger.error(f"Failed to process attachment: {e}")
                        continue

            # 2. Inline/CID images (MIME parts without filenames)
            inline_images = extract_inline_images(msg)
            for inline_part in inline_images:
                try:
                    result = process_attachment(
                        client=client,
                        gmail_service=service,
                        email_id=email_id,
                        message_id=provider_message_id,
                        attachment_part=inline_part,
                        config=config,
                    )
                    if result:
                        images_stored += 1
                except AttachmentError as e:
                    logger.error(f"Failed to process inline image: {e}")
                    continue

            # Get HTML body for linked and data URI extraction
            parsed_email = provider_message_id_to_parsed.get(provider_message_id, {})
            body_html = parsed_email.get("body_html")

            if body_html:
                # 3. Linked images (http/https URLs in HTML)
                try:
                    linked_images = extract_linked_images(body_html)
                    for idx, img in enumerate(linked_images):
                        ext = img.mime_type.split("/")[-1]
                        filename = f"linked_{idx}.{ext}"
                        try:
                            result = store_image_content(
                                client=client,
                                email_id=email_id,
                                image_data=img.data,
                                mime_type=img.mime_type,
                                filename=filename,
                                config=config,
                            )
                            if result:
                                images_stored += 1
                        except AttachmentError as e:
                            logger.error(f"Failed to store linked image: {e}")
                            continue
                except Exception as e:
                    logger.warning(f"Failed to extract linked images: {e}")

                # 4. Data URI images (base64-encoded in HTML)
                try:
                    data_uri_images = extract_data_uri_images(body_html)
                    for idx, img in enumerate(data_uri_images):
                        ext = img.mime_type.split("/")[-1]
                        filename = f"data_uri_{idx}.{ext}"
                        try:
                            result = store_image_content(
                                client=client,
                                email_id=email_id,
                                image_data=img.data,
                                mime_type=img.mime_type,
                                filename=filename,
                                config=config,
                            )
                            if result:
                                images_stored += 1
                        except AttachmentError as e:
                            logger.error(f"Failed to store data URI image: {e}")
                            continue
                except Exception as e:
                    logger.warning(f"Failed to extract data URI images: {e}")

            # Update has_attachments if we stored images for an email that
            # didn't originally report having attachments
            if images_stored > 0 and not email_record.get("has_attachments"):
                try:
                    client.table("emails").update(
                        {"has_attachments": True}
                    ).eq("id", email_id).execute()
                    logger.debug(f"Updated has_attachments=True for email {email_id}")
                except Exception as e:
                    logger.warning(f"Failed to update has_attachments: {e}")

            if images_stored > 0:
                attachments_downloaded += images_stored
                logger.info(f"Stored {images_stored} images for email {email_id}")

        logger.info(f"Downloaded {attachments_downloaded} attachments/images")

    return {
        "fetched": len(messages),
        "saved": len(saved_records),
        "attachments_downloaded": attachments_downloaded,
    }


# --- Status-based worker claiming functions ---


def claim_pending_email(
    client: Client,
    worker_id: str,
    lock_duration_seconds: int = 300,
) -> Optional[dict[str, Any]]:
    """Atomically claim the next pending email for processing.

    Uses PostgreSQL FOR UPDATE SKIP LOCKED to safely claim emails without
    conflicts between multiple workers.

    Args:
        client: Authenticated Supabase client (should use service role).
        worker_id: Unique identifier for this worker process.
        lock_duration_seconds: How long to hold the lock (default: 5 minutes).

    Returns:
        Email dict if claimed, None if no pending emails available.

    Raises:
        EmailError: If claim operation fails.
    """
    try:
        result = client.rpc('claim_unprocessed_email', {
            'p_worker_id': worker_id,
            'p_lock_duration_seconds': lock_duration_seconds,
        }).execute()

        if result.data and len(result.data) > 0:
            email = result.data[0]
            subject = email.get("subject", "(no subject)")[:50]
            logger.info(
                f"Worker {worker_id} claimed email {email['id']}: {subject} "
                f"(attempt {email['attempts']}/{email['max_attempts']})"
            )
            return email

        return None

    except Exception as e:
        raise EmailError(f"Failed to claim pending email: {e}") from e


def complete_email_processing(client: Client, email_id: str) -> None:
    """Mark email as processed successfully and clear the lock.

    Args:
        client: Authenticated Supabase client (should use service role).
        email_id: UUID of email to mark as processed.

    Raises:
        EmailError: If update fails.
    """
    try:
        client.table("emails").update({
            "processing_status": "processed",
            "processing_error": None,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "locked_by": None,
            "locked_until": None,
        }).eq("id", email_id).execute()

        logger.info(f"Completed processing email {email_id}")

    except Exception as e:
        raise EmailError(f"Failed to complete email processing: {e}") from e


def fail_email_processing(
    client: Client,
    email_id: str,
    error: str,
) -> None:
    """Mark email processing as failed.

    If attempts < max_attempts, sets status back to 'pending' for retry.
    Otherwise, sets status to 'failed' permanently.

    Args:
        client: Authenticated Supabase client (should use service role).
        email_id: UUID of email that failed processing.
        error: Error message to store.

    Raises:
        EmailError: If update fails.
    """
    try:
        # Fetch current email to check retry eligibility
        result = client.table("emails").select(
            "attempts, max_attempts"
        ).eq("id", email_id).single().execute()

        email = result.data
        attempts = email["attempts"]
        max_attempts = email["max_attempts"]
        should_retry = attempts < max_attempts

        update_data = {
            "processing_status": "pending" if should_retry else "failed",
            "processing_error": error,
            "locked_by": None,
            "locked_until": None,
        }

        if should_retry:
            delay, next_retry_at = calculate_retry_delay(attempts)
            update_data["next_retry_at"] = next_retry_at
        else:
            # Dead letter: permanently failed
            update_data["dead_letter_reason"] = error
            update_data["dead_letter_at"] = datetime.now(timezone.utc).isoformat()

        client.table("emails").update(update_data).eq("id", email_id).execute()

        if should_retry:
            logger.warning(
                f"Email {email_id} processing failed "
                f"(attempt {attempts}/{max_attempts}): {error}. "
                f"Will retry in {delay}s."
            )
        else:
            logger.error(
                f"Email {email_id} processing failed permanently "
                f"after {attempts} attempts: {error}. "
                f"Moved to dead letter."
            )

    except Exception as e:
        raise EmailError(f"Failed to mark email as failed: {e}") from e


def skip_email_processing(client: Client, email_id: str) -> None:
    """Mark email as skipped (e.g., sender ignored).

    Args:
        client: Authenticated Supabase client (should use service role).
        email_id: UUID of email to skip.

    Raises:
        EmailError: If update fails.
    """
    try:
        client.table("emails").update({
            "processing_status": "skipped",
            "locked_by": None,
            "locked_until": None,
        }).eq("id", email_id).execute()

        logger.info(f"Skipped email {email_id}")

    except Exception as e:
        raise EmailError(f"Failed to skip email: {e}") from e


def unlock_expired_email_locks(client: Client) -> int:
    """Reset expired email locks back to pending.

    Handles the case where a worker crashes mid-processing and the lock expires.

    Args:
        client: Authenticated Supabase client (should use service role).

    Returns:
        Number of emails unlocked.

    Raises:
        EmailError: If unlock fails.
    """
    try:
        result = client.rpc('unlock_expired_email_locks').execute()
        count = result.data if result.data else 0

        if count > 0:
            logger.warning(f"Unlocked {count} expired email locks")

        return count

    except Exception as e:
        raise EmailError(f"Failed to unlock expired email locks: {e}") from e
