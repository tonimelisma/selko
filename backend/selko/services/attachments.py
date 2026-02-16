"""Attachment service for Selko.

Handles downloading attachments from Gmail, uploading to Supabase Storage,
and managing attachment metadata with content deduplication.
"""

import base64
import hashlib
import logging
import time
from typing import Any, Optional
from uuid import uuid4

from googleapiclient.errors import HttpError
from supabase import Client, PostgrestAPIError

from selko.config import Config
from selko.services.auth import get_current_user_id

logger = logging.getLogger(__name__)


class AttachmentError(Exception):
    """Raised when attachment operations fail."""

    pass


def calculate_content_hash(data: bytes) -> str:
    """Calculate SHA-256 hash of attachment content for deduplication.

    Args:
        data: Raw attachment bytes.

    Returns:
        Hex-encoded SHA-256 hash string.
    """
    return hashlib.sha256(data).hexdigest()


def check_duplicate_attachment(
    client: Client,
    content_hash: str,
) -> Optional[dict]:
    """Check if attachment with same hash already exists for user.

    Args:
        client: Authenticated Supabase client.
        content_hash: SHA-256 hash to check.

    Returns:
        Existing attachment record if found, None otherwise.
    """
    try:
        result = (
            client.table("attachments")
            .select("*")
            .eq("content_hash", content_hash)
            .limit(1)
            .execute()
        )
        if result.data:
            logger.debug(f"Found duplicate attachment with hash: {content_hash[:16]}...")
            return result.data[0]
        return None
    except PostgrestAPIError as e:
        logger.warning(f"Error checking for duplicate: {e.message}")
        return None


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
    client: Client,
    user_id: str,
    filename: str,
    data: bytes,
    mime_type: str,
    bucket: str = "attachments",
) -> str:
    """Upload attachment to Supabase Storage.

    Args:
        client: Authenticated Supabase client.
        user_id: User UUID for path namespacing.
        filename: Original filename.
        data: File bytes.
        mime_type: MIME type.
        bucket: Storage bucket name.

    Returns:
        Storage path (e.g., "{user_id}/{uuid}_{filename}").

    Raises:
        AttachmentError: If upload fails.
    """
    # Generate unique filename with user namespace
    # Sanitize filename: remove path separators and limit length
    safe_filename = filename.replace("/", "_").replace("\\", "_")[:100]
    unique_id = uuid4().hex[:12]
    storage_path = f"{user_id}/{unique_id}_{safe_filename}"

    try:
        client.storage.from_(bucket).upload(
            path=storage_path,
            file=data,
            file_options={"content-type": mime_type},
        )
        logger.debug(f"Uploaded attachment to {storage_path}")
        return storage_path

    except Exception as e:
        raise AttachmentError(f"Failed to upload attachment: {e}") from e


def save_attachment_metadata(
    client: Client,
    email_id: str,
    gmail_attachment_id: str,
    filename: str,
    mime_type: str,
    size_bytes: int,
    storage_path: str,
    content_hash: str,
) -> dict:
    """Save attachment metadata to database.

    Args:
        client: Authenticated Supabase client.
        email_id: UUID of parent email record.
        gmail_attachment_id: Gmail's attachment ID.
        filename: Original filename.
        mime_type: MIME type.
        size_bytes: File size in bytes.
        storage_path: Path in Supabase Storage.
        content_hash: SHA-256 hash for deduplication.

    Returns:
        Created attachment record.

    Raises:
        AttachmentError: If database insert fails.
    """
    user_id = get_current_user_id(client)

    record = {
        "user_id": user_id,
        "email_id": email_id,
        "gmail_attachment_id": gmail_attachment_id,
        "filename": filename,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "storage_path": storage_path,
        "content_hash": content_hash,
    }

    try:
        result = client.table("attachments").insert(record).execute()
        if result.data:
            logger.debug(f"Saved attachment metadata: {filename}")
            return result.data[0]
        raise AttachmentError("Insert returned no data")

    except PostgrestAPIError as e:
        raise AttachmentError(f"Failed to save attachment metadata: {e.message}") from e


def process_attachment(
    client: Client,
    gmail_service,
    email_id: str,
    message_id: str,
    attachment_part: dict[str, Any],
    config: Config,
) -> Optional[dict]:
    """Process a single email attachment end-to-end.

    This is the main orchestration function that:
    1. Downloads attachment from Gmail
    2. Calculates content hash
    3. Checks for duplicates
    4. Uploads to storage (if new)
    5. Saves metadata to database

    Args:
        client: Authenticated Supabase client.
        gmail_service: Gmail API service.
        email_id: UUID of parent email in database.
        message_id: Gmail message ID.
        attachment_part: Attachment metadata dict with keys:
            - attachment_id: Gmail attachment ID
            - filename: Original filename
            - mime_type: MIME type
            - size_bytes: Size in bytes
        config: Application config.

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

    # Calculate hash
    content_hash = calculate_content_hash(data)
    logger.debug(f"Content hash: {content_hash[:16]}...")

    # Check for duplicates
    existing = check_duplicate_attachment(client, content_hash)
    if existing:
        logger.info(f"Skipping duplicate attachment: {filename} (hash match)")
        return existing

    # Upload to storage
    user_id = get_current_user_id(client)
    storage_path = upload_to_storage(
        client=client,
        user_id=user_id,
        filename=filename,
        data=data,
        mime_type=mime_type,
        bucket=config.storage_bucket_attachments,
    )

    # Save metadata
    record = save_attachment_metadata(
        client=client,
        email_id=email_id,
        gmail_attachment_id=attachment_id,
        filename=filename,
        mime_type=mime_type,
        size_bytes=len(data),  # Use actual size from downloaded data
        storage_path=storage_path,
        content_hash=content_hash,
    )

    logger.info(f"Saved new attachment: {filename}")
    return record


def store_image_content(
    client: Client,
    email_id: str,
    image_data: bytes,
    mime_type: str,
    filename: str,
    config: Config,
) -> Optional[dict]:
    """Store image data directly as an attachment (no Gmail API download needed).

    For linked images and data URIs that are already downloaded/decoded.
    Uses content hash deduplication like process_attachment().

    Args:
        client: Authenticated Supabase client.
        email_id: UUID of parent email record.
        image_data: Raw image bytes.
        mime_type: Image MIME type.
        filename: Filename for the stored image.
        config: Application config.

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

    content_hash = calculate_content_hash(image_data)

    # Check for duplicates
    existing = check_duplicate_attachment(client, content_hash)
    if existing:
        logger.debug(f"Skipping duplicate image: {filename} (hash match)")
        return existing

    # Upload to storage
    user_id = get_current_user_id(client)
    storage_path = upload_to_storage(
        client=client,
        user_id=user_id,
        filename=filename,
        data=image_data,
        mime_type=mime_type,
        bucket=config.storage_bucket_attachments,
    )

    # Save metadata (no gmail_attachment_id for non-Gmail images)
    record = save_attachment_metadata(
        client=client,
        email_id=email_id,
        gmail_attachment_id="",
        filename=filename,
        mime_type=mime_type,
        size_bytes=len(image_data),
        storage_path=storage_path,
        content_hash=content_hash,
    )

    logger.info(f"Stored image: {filename} ({len(image_data)} bytes)")
    return record


def delete_attachment(client: Client, attachment_id: str, config: Config) -> bool:
    """Delete an attachment from storage and database.

    Args:
        client: Authenticated Supabase client.
        attachment_id: UUID of attachment record.
        config: Application config.

    Returns:
        True if deleted successfully, False otherwise.
    """
    try:
        # Get attachment record
        result = (
            client.table("attachments")
            .select("storage_path")
            .eq("id", attachment_id)
            .single()
            .execute()
        )

        if not result.data:
            logger.warning(f"Attachment not found: {attachment_id}")
            return False

        storage_path = result.data.get("storage_path")

        # Delete from storage
        if storage_path:
            try:
                client.storage.from_(config.storage_bucket_attachments).remove(
                    [storage_path]
                )
                logger.debug(f"Deleted from storage: {storage_path}")
            except Exception as e:
                logger.warning(f"Failed to delete from storage: {e}")

        # Delete from database
        client.table("attachments").delete().eq("id", attachment_id).execute()
        logger.info(f"Deleted attachment: {attachment_id}")
        return True

    except PostgrestAPIError as e:
        logger.error(f"Failed to delete attachment: {e.message}")
        return False
