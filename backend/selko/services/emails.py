"""Email service for Selko.

Handles email parsing and database storage.
"""

import base64
import logging
import re
from datetime import datetime, timezone
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from typing import Any, Optional

from selko.config import Config
from selko.db import emails as db_emails
from selko.db.connection import Database
from selko.services.email_body import select_body_text
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

    # Add body columns if content was found. The text/plain part is not
    # trusted on its own: a multipart/alternative whose plain part is a
    # placeholder (Ticketmaster sends the single word "Ticketmaster") would
    # otherwise store 14 bytes and starve extraction of the entire message,
    # which is exactly how "You Got Tickets To Monster Jam" produced no event.
    # select_body_text renders the HTML part when it says more.
    selected_body_text = select_body_text(body_text, body_html)
    if selected_body_text:
        result["body_text"] = selected_body_text
    # body_html still intentionally not persisted (Inc1 payload fix) — linked
    # images are extracted in-memory from payload, not from DB, and the text
    # we need from it is now rendered above rather than stored twice.

    invite_method = _detect_gmail_invite_method(payload)
    result["is_calendar_invite"] = invite_method in INVITE_METHODS
    if result["is_calendar_invite"]:
        mark_parsed_as_calendar_invite(result)

    return result


def fetch_emails_for_user(
    client: Database,
    config: Config,
    max_results: int = 10,
    fetch_attachments: bool = True,
    user_id: str | None = None,
) -> dict[str, int]:
    """Request a prompt provider poll for this user's email integrations.

    Manual sync used to run its own Gmail fetch, which bypassed the durable
    cursors and made the API a second writer alongside the poller. Discovery is
    now owned exclusively by the ingestion coordinator, so this just brings the
    next poll forward; the coordinator picks it up on its next tick and results
    surface through the normal History flow.

    `max_results` and `fetch_attachments` are accepted for API compatibility
    and ignored: scan breadth is governed by the poll and reconciliation
    windows, and attachments are fetched by their own workers.

    Args:
        client: The process database.
        config: Configuration object.
        max_results: Ignored; retained for API compatibility.
        fetch_attachments: Ignored; retained for API compatibility.
        user_id: Integration owner (required).

    Returns:
        Dict with zeroed counts: ingestion is asynchronous, so nothing is
        fetched inline.

    Raises:
        NoGmailIntegrationError: If the user has no Gmail integration.
        EmailError: If the sync request could not be recorded.
    """
    if user_id is None:
        raise EmailError("fetch_emails_for_user needs the owning user_id")

    try:
        integrations = db_emails.active_mail_integrations(client, user_id)
    except Exception as e:
        raise EmailError(f"Error loading email integrations: {e}") from e

    if not any(row.get("provider") == "gmail" for row in integrations):
        raise NoGmailIntegrationError(
            "No Gmail integration found. Please authenticate with Gmail first."
        )

    try:
        for row in integrations:
            # A live lease means a run is already under way; leave it alone.
            db_emails.request_poll(client, row["id"])
    except Exception as e:
        raise EmailError(f"Error requesting email sync: {e}") from e

    logger.info("Requested prompt email poll for %d integration(s)", len(integrations))
    return {"fetched": 0, "saved": 0, "attachments_downloaded": 0}



# --- Status-based worker claiming functions ---


async def claim_pending_email(
    pool,
    worker_id: str,
    lock_duration_seconds: int = 300,
) -> Optional[dict[str, Any]]:
    """Atomically claim the next pending email for processing.

    The claim runs in the single writer transaction, so two workers can never
    take the same row. One implementation: `selko.db.emails.claim_unprocessed_email`.

    Args:
        pool: The process database.
        worker_id: Unique identifier for this worker process.
        lock_duration_seconds: How long to hold the lock (default: 5 minutes).

    Returns:
        Email dict if claimed, None if no pending emails available.

    Raises:
        EmailError: If claim operation fails.
    """
    try:
        email = await pool.run(
            db_emails.claim_unprocessed_email, pool, worker_id, lock_duration_seconds
        )
        if email:
            logger.info(
                f"Worker {worker_id} claimed email {email['id']} "
                f"(attempt {email.get('attempts', 0)}/{email.get('max_attempts', 0)})"
            )
            return email
        return None

    except Exception as e:
        raise EmailError(f"Failed to claim pending email: {e}") from e


async def complete_email_processing(pool, email_id: str) -> None:
    """Mark email as processed successfully and clear the lock.

    Args:
        pool: The process database.
        email_id: UUID of email to mark as processed.

    Raises:
        EmailError: If update fails.
    """
    try:
        await pool.run(db_emails.complete_email_processing, pool, email_id)
        logger.info(f"Completed processing email {email_id}")

    except Exception as e:
        raise EmailError(f"Failed to complete email processing: {e}") from e


async def fail_email_processing(
    pool,
    email_id: str,
    worker_id: str,
    generation: int,
    error: str,
    retry_base_seconds: int,
    retry_max_seconds: int,
) -> dict[str, Any]:
    """Fenced retry-or-terminate transition for a claimed email.

    Delegates the retry-vs-terminal decision and the row mutation to
    `selko.db.emails.fail_email_processing`, one transaction. Only the
    ``(worker_id, generation)`` that currently owns the row's lease may
    transition it; a stale caller's request is a no-op (``fenced: true`` in
    the returned dict) so a replacement worker's claim is never overwritten.

    Args:
        pool: The process database.
        email_id: UUID of email that failed processing.
        worker_id: Identifier of the worker that holds the claim.
        generation: Lease generation the worker claimed (``lock_generation``).
        error: Error message to store.
        retry_base_seconds: Base delay for exponential backoff.
        retry_max_seconds: Cap for exponential backoff.

    Returns:
        ``{fenced, status, attempts, next_retry_at?}``.

    Raises:
        EmailError: If the transition fails.
    """
    try:
        outcome = await pool.run(
            db_emails.fail_email_processing, pool, email_id, worker_id, generation,
            error, error, retry_base_seconds, retry_max_seconds,
        )
        if outcome.get("fenced"):
            logger.warning(
                f"Email {email_id} failure ignored: worker {worker_id} "
                f"generation {generation} no longer owns the lease"
            )
        elif outcome.get("status") == "pending":
            logger.warning(
                f"Email {email_id} processing failed "
                f"(attempt {outcome.get('attempts')}): {error}. "
                f"Will retry at {outcome.get('next_retry_at')}."
            )
        else:
            logger.error(
                f"Email {email_id} processing failed permanently "
                f"after {outcome.get('attempts')} attempts: {error}. "
                f"Moved to dead letter."
            )
        return outcome

    except Exception as e:
        raise EmailError(f"Failed to mark email as failed: {e}") from e


async def unlock_expired_email_locks(pool) -> int:
    """Reset expired email locks back to pending.

    Handles the case where a worker crashes mid-processing and the lock expires.

    Args:
        pool: The process database.

    Returns:
        Number of emails unlocked.

    Raises:
        EmailError: If unlock fails.
    """
    try:
        count = await pool.run(db_emails.unlock_expired_email_locks, pool)

        if count:
            logger.warning(f"Unlocked {count} expired email locks")

        return count or 0

    except Exception as e:
        raise EmailError(f"Failed to unlock expired email locks: {e}") from e
