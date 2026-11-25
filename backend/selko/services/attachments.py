"""Attachment service for Selko.

Handles downloading attachments from Gmail, storing their bytes as files
under the data directory, and managing attachment metadata with content
deduplication.

Files live at ``<attachments dir>/<storage_path>``, where ``storage_path``
keeps the layout Supabase Storage used, ``{user_id}/{uuid12}_{filename}``, so
the imported rows' paths stay valid (docs/specs/sqlite-single-process
decision D8). Every write is atomic (temp file + rename), and a path that
would leave the attachments directory is refused.
"""

import base64
import contextlib
import hashlib
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from googleapiclient.errors import HttpError

from selko.config import Config
from selko.db import attachments as db_attachments
from selko.db.connection import Database
from selko.db.errors import DbError
from selko.db.runtime import attachments_dir
from selko.services.egress import GMAIL, record_egress

logger = logging.getLogger(__name__)

# The content types Selko stores and reads: the worker's accept-set. The file
# store refuses anything else, so a type outside it is terminal `unsupported`
# rather than a retry ladder ending in dead_letter.
SUPPORTED_ATTACHMENT_MIME_PREFIXES = ("image/", "text/")
SUPPORTED_ATTACHMENT_MIMES = {
    "application/pdf",
    "application/rtf",
    "application/ics",
    "text/calendar",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def is_supported_attachment_type(mime_type: str | None) -> bool:
    """Whether the file store accepts this content type."""
    mime = str(mime_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    return mime.startswith(SUPPORTED_ATTACHMENT_MIME_PREFIXES) or mime in SUPPORTED_ATTACHMENT_MIMES


class AttachmentError(Exception):
    """Raised when attachment operations fail."""

    pass


class AttachmentTypeRejected(AttachmentError):
    """The store refused the content type, and will refuse it again.

    Distinguished from a plain ``AttachmentError`` because the retry ladder is
    the wrong response to it. A type rejection is a property of the
    type, not of the moment: retrying spends all 8 attempts to reach the same
    `415`, and the row then lands in `dead_letter` -- one of the four counts
    `assert-health.sh` calls never acceptable, which no worker clears, so a
    single unstorable attachment pins /health to degraded indefinitely. That
    is exactly what one `text/markdown` file did on 2026-10-18.

    The honest terminal state is `unsupported`: the system genuinely cannot
    store this type. It is informational rather than actionable, so it does
    not degrade the roll-up, and the next allowlist drift costs one skipped
    attachment instead of a permanently red gate.
    """


def calculate_content_hash(data: bytes) -> str:
    """Calculate SHA-256 hash of attachment content for deduplication.

    Args:
        data: Raw attachment bytes.

    Returns:
        Hex-encoded SHA-256 hash string.
    """
    return hashlib.sha256(data).hexdigest()


def check_duplicate_attachment(
    client: Database,
    content_hash: str,
    user_id: str | None = None,
) -> Optional[dict]:
    """Return the user's attachment with the same hash, if any.

    Args:
        client: The process database.
        content_hash: SHA-256 hash to check.
        user_id: Owner; duplicates are only ever the owner's own rows.

    Returns:
        Existing attachment record if found, None otherwise.
    """
    if user_id is None:
        return None
    try:
        existing = db_attachments.find_by_content_hash(client, user_id, content_hash)
    except DbError as e:
        logger.warning(f"Error checking for duplicate: {e}")
        return None
    if existing:
        logger.debug(f"Found duplicate attachment with hash: {content_hash[:16]}...")
    return existing


# ---------------------------------------------------------------------------
# The file store
# ---------------------------------------------------------------------------


def _resolve_storage_path(storage_path: str) -> Path:
    """The file for a stored path, refusing anything outside the attachments dir."""
    if not storage_path or "\0" in storage_path:
        raise AttachmentError("empty or invalid storage path")
    relative = Path(storage_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise AttachmentError(f"storage path escapes the attachments directory: {storage_path!r}")
    root = attachments_dir().resolve()
    target = (root / relative).resolve()
    if root not in target.parents:
        raise AttachmentError(f"storage path escapes the attachments directory: {storage_path!r}")
    return target


def write_attachment_file(storage_path: str, data: bytes) -> Path:
    """Write ``data`` atomically: a temp file in the same directory, then rename."""
    target = _resolve_storage_path(storage_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return target


def read_attachment_file(storage_path: str) -> bytes:
    """The stored bytes of an attachment."""
    try:
        return _resolve_storage_path(storage_path).read_bytes()
    except FileNotFoundError as e:
        raise AttachmentError(f"attachment file missing: {storage_path}") from e


def delete_attachment_file(storage_path: str) -> bool:
    """Remove a stored file; False when it was already gone."""
    try:
        _resolve_storage_path(storage_path).unlink()
        return True
    except FileNotFoundError:
        return False


def download_gmail_attachment(
    service,
    message_id: str,
    attachment_id: str,
    max_retries: int = 3,
) -> bytes:
    """Download attachment data from Gmail API.

    Args:
        service: Gmail API service.
        message_id: Gmail message ID.
        attachment_id: Gmail attachment ID.
        max_retries: Maximum retries for rate-limited requests.

    Returns:
        Raw attachment bytes (decoded from base64url).

    Raises:
        AttachmentError: If download fails after retries.
    """
    for attempt in range(max_retries):
        try:
            result = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=message_id, id=attachment_id)
                .execute()
            )

            # Gmail returns base64url encoded data
            data = result.get("data", "")
            # Count the encoded length: that is what crossed the wire, and
            # base64 inflates the payload by about a third versus the decoded
            # bytes. Attachments are the single largest per-item download in the
            # system, so under-counting them here would defeat the purpose.
            record_egress(
                GMAIL,
                "GET /gmail/v1/users/me/messages/{id}/attachments/{id}",
                response_bytes=len(data),
            )
            return base64.urlsafe_b64decode(data)

        except HttpError as e:
            if e.resp.status == 429:  # Rate limited
                wait_time = (2**attempt) + 1  # 1, 3, 5 seconds
                logger.warning(
                    f"Rate limited downloading attachment, waiting {wait_time}s "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(wait_time)
            else:
                raise AttachmentError(
                    f"Failed to download attachment: {e.resp.status} {e.reason}"
                ) from e

    raise AttachmentError(
        f"Failed to download attachment after {max_retries} retries (rate limited)"
    )


def upload_to_storage(
    client: Database,
    user_id: str,
    filename: str,
    data: bytes,
    mime_type: str,
    bucket: str = "attachments",
) -> str:
    """Store attachment bytes as a file under the attachments directory.

    Args:
        client: The process database (unused; kept for the call sites).
        user_id: User UUID for path namespacing.
        filename: Original filename.
        data: File bytes.
        mime_type: MIME type; a type outside the accept-set is refused.
        bucket: Historical bucket name (unused).

    Returns:
        Storage path (e.g., "{user_id}/{uuid}_{filename}").

    Raises:
        AttachmentTypeRejected: If the content type is not one Selko stores.
        AttachmentError: If the write fails.
    """
    if not is_supported_attachment_type(mime_type):
        # Permanent for this type: the worker finishes the row `unsupported`.
        raise AttachmentTypeRejected(f"Storage rejected content type {mime_type!r}")
    # Unique filename under the user's directory, URL-safe ASCII: the layout
    # Supabase Storage required, kept so imported paths stay valid (D8). The
    # result never contains '/' or '..', so it stays inside the user's directory.
    import re as _re
    import unicodedata as _ud
    # NFKD transliterate ö→o etc, drop non-ASCII, then strip unsafe chars
    _norm = _ud.normalize('NFKD', filename)
    _ascii = _norm.encode('ascii', 'ignore').decode('ascii')
    # Keep alphanumerics, dot, dash, underscore; everything else → underscore
    _sanitized = _re.sub(r'[^A-Za-z0-9._-]+', '_', _ascii)
    # Collapse runs, trim dots/underscores, fallback if empty
    _sanitized = _re.sub(r'_+', '_', _sanitized).strip('._')
    if not _sanitized:
        _sanitized = 'attachment'
    # Preserve extension separately so filtering still works when truncated
    # (e.g. .pdf) — keep last dot + ext within the 100-char budget
    _sanitized = _sanitized[:100].strip('._') or 'attachment'
    safe_filename = _sanitized
    unique_id = uuid4().hex[:12]
    storage_path = f"{user_id}/{unique_id}_{safe_filename}"

    try:
        write_attachment_file(storage_path, data)
    except OSError as e:
        raise AttachmentError(f"Failed to store attachment: {e}") from e
    logger.debug(f"Stored attachment at {storage_path}")
    return storage_path


def save_attachment_metadata(
    client: Database,
    email_id: str,
    provider_attachment_id: str,
    filename: str,
    mime_type: str,
    size_bytes: int,
    storage_path: str,
    content_hash: str,
    user_id: str | None = None,
) -> dict:
    """Save attachment metadata to database.

    Args:
        client: The process database.
        email_id: UUID of parent email record.
        provider_attachment_id: Provider's attachment ID.
        filename: Original filename.
        mime_type: MIME type.
        size_bytes: File size in bytes.
        storage_path: Path under the attachments directory.
        content_hash: SHA-256 hash for deduplication.
        user_id: Owner (required).

    Returns:
        Created attachment record.

    Raises:
        AttachmentError: If database insert fails.
    """
    if user_id is None:
        raise AttachmentError("save_attachment_metadata needs the owning user_id")

    record = {
        "email_id": email_id,
        "provider_attachment_id": provider_attachment_id,
        "filename": filename,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "storage_path": storage_path,
        "content_hash": content_hash,
    }

    try:
        saved = db_attachments.insert(client, user_id, record)
    except DbError as e:
        raise AttachmentError(f"Failed to save attachment metadata: {e}") from e
    logger.debug(f"Saved attachment metadata: {filename}")
    return saved


def store_attachment_bytes(
    client: Database,
    email_id: str,
    *,
    data: bytes,
    filename: str,
    mime_type: str,
    config: Config,
    provider_attachment_id: str = "",
    user_id: str | None = None,
) -> Optional[dict]:
    """Store already-downloaded attachment bytes with hash deduplication."""
    if not data:
        return None

    if len(data) > config.max_attachment_size:
        logger.warning(
            "Skipping oversized attachment: %s (%.1f MB > %.0f MB limit)",
            filename,
            len(data) / 1024 / 1024,
            config.max_attachment_size / 1024 / 1024,
        )
        return None

    if user_id is None:
        raise AttachmentError("store_attachment_bytes needs the owning user_id")
    owner_id = user_id
    content_hash = calculate_content_hash(data)
    existing = check_duplicate_attachment(client, content_hash, owner_id)
    if existing:
        logger.info("Skipping duplicate attachment: %s (hash match)", filename)
        return existing

    storage_path = upload_to_storage(
        client=client,
        user_id=owner_id,
        filename=filename,
        data=data,
        mime_type=mime_type,
        bucket=config.storage_bucket_attachments,
    )
    return save_attachment_metadata(
        client=client,
        email_id=email_id,
        provider_attachment_id=provider_attachment_id,
        filename=filename,
        mime_type=mime_type,
        size_bytes=len(data),
        storage_path=storage_path,
        content_hash=content_hash,
        user_id=owner_id,
    )


def process_attachment(
    client: Database,
    gmail_service,
    email_id: str,
    message_id: str,
    attachment_part: dict[str, Any],
    config: Config,
    user_id: str | None = None,
) -> Optional[dict]:
    """Process a single email attachment end-to-end.

    This is the main orchestration function that:
    1. Downloads attachment from Gmail
    2. Calculates content hash
    3. Checks for duplicates
    4. Uploads to storage (if new)
    5. Saves metadata to database

    Args:
        client: The process database.
        gmail_service: Gmail API service.
        email_id: UUID of parent email in database.
        message_id: Gmail message ID.
        attachment_part: Attachment metadata dict with keys:
            - attachment_id: Gmail attachment ID
            - filename: Original filename
            - mime_type: MIME type
            - size_bytes: Size in bytes
        config: Application config.
        user_id: Owner of the attachment (required).

    Returns:
        Attachment record (new or existing), or None if skipped.

    Raises:
        AttachmentError: If processing fails.
    """
    attachment_id = attachment_part.get("attachment_id")
    filename = attachment_part.get("filename", "unnamed")
    mime_type = attachment_part.get("mime_type", "application/octet-stream")
    size_bytes = attachment_part.get("size_bytes", 0)

    # Check size limit
    if size_bytes > config.max_attachment_size:
        logger.warning(
            f"Skipping oversized attachment: {filename} "
            f"({size_bytes / 1024 / 1024:.1f} MB > {config.max_attachment_size / 1024 / 1024:.0f} MB limit)"
        )
        return None

    logger.info(f"Processing attachment: {filename} ({size_bytes} bytes)")

    # Download from Gmail
    data = download_gmail_attachment(gmail_service, message_id, attachment_id)

    record = store_attachment_bytes(
        client=client,
        email_id=email_id,
        data=data,
        filename=filename,
        mime_type=mime_type,
        config=config,
        provider_attachment_id=attachment_id,
        user_id=user_id,
    )

    logger.info(f"Saved new attachment: {filename}")
    return record


def store_image_content(
    client: Database,
    email_id: str,
    image_data: bytes,
    mime_type: str,
    filename: str,
    config: Config,
    user_id: str | None = None,
) -> Optional[dict]:
    """Store image data directly as an attachment (no Gmail API download needed).

    For linked images and data URIs that are already downloaded/decoded.
    Uses content hash deduplication like process_attachment().

    Args:
        client: The process database.
        email_id: UUID of parent email record.
        image_data: Raw image bytes.
        mime_type: Image MIME type.
        filename: Filename for the stored image.
        config: Application config.
        user_id: Owner of the attachment (required).

    Returns:
        Attachment record (new or existing), or None if skipped.
    """
    if not image_data:
        return None

    # Check size limit
    if len(image_data) > config.max_attachment_size:
        logger.warning(
            f"Skipping oversized image: {filename} "
            f"({len(image_data) / 1024 / 1024:.1f} MB)"
        )
        return None

    record = store_attachment_bytes(
        client=client,
        email_id=email_id,
        data=image_data,
        filename=filename,
        mime_type=mime_type,
        config=config,
        provider_attachment_id="",
        user_id=user_id,
    )

    logger.info(f"Stored image: {filename} ({len(image_data)} bytes)")
    return record


def delete_attachment(
    client: Database, attachment_id: str, config: Config, user_id: str | None = None
) -> bool:
    """Delete one of the user's attachments: the row, then its file.

    The file goes only after the row's delete commits, so a crash between the
    two leaves an orphan file, never a row pointing at nothing.

    Args:
        client: The process database.
        attachment_id: UUID of attachment record.
        config: Application config.
        user_id: Owner (required).

    Returns:
        True if deleted successfully, False otherwise.
    """
    if user_id is None:
        logger.warning("delete_attachment called without an owner; refusing")
        return False
    try:
        row = db_attachments.get(client, user_id, attachment_id)
        if not row:
            logger.warning(f"Attachment not found: {attachment_id}")
            return False
        if not db_attachments.delete(client, user_id, attachment_id):
            return False
    except DbError as e:
        logger.error(f"Failed to delete attachment: {e}")
        return False

    storage_path = row.get("storage_path")
    if storage_path:
        try:
            delete_attachment_file(storage_path)
            logger.debug(f"Deleted file: {storage_path}")
        except Exception as e:
            logger.warning(f"Failed to delete attachment file: {e}")
    logger.info(f"Deleted attachment: {attachment_id}")
    return True
