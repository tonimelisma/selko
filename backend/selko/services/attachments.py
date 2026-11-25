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
from uuid import uuid4

from googleapiclient.errors import HttpError

from selko.db.connection import Database
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


# ---------------------------------------------------------------------------
# The file store
# ---------------------------------------------------------------------------


def _resolve_storage_path(storage_path: str, root: Path | None = None) -> Path:
    """The file for a stored path, refusing anything outside the attachments dir."""
    if not storage_path or "\0" in storage_path:
        raise AttachmentError("empty or invalid storage path")
    relative = Path(storage_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise AttachmentError(f"storage path escapes the attachments directory: {storage_path!r}")
    root = (root or attachments_dir()).resolve()
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


def read_attachment_file(storage_path: str, root: Path | None = None) -> bytes:
    """The stored bytes of an attachment (``root``: the attachments directory,
    default the process database's)."""
    try:
        return _resolve_storage_path(storage_path, root).read_bytes()
    except FileNotFoundError as e:
        raise AttachmentError(f"attachment file missing: {storage_path}") from e


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

