"""Photos service for Selko.

Handles photo data operations: saving metadata and updating processing
status. Google Photos ingestion is parked; the claim
(``claim_pending_photo``) had no caller and was not ported
(docs/specs/sqlite-single-process/02-data-layer.md §2.12).
"""

import logging
from typing import Any, Optional

from selko.db import parked as db_parked
from selko.db.connection import Database
from selko.db.errors import DbError

Client = Database

logger = logging.getLogger(__name__)


class PhotosError(Exception):
    """Raised when photo operations fail."""

    pass


def save_photo_metadata(
    client: Client,
    user_id: str,
    photo_data: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Save photo record to photos table, handling duplicates via google_photo_id.

    Uses upsert to handle the case where a photo already exists (re-fetch).

    Args:
        client: The process database.
        user_id: UUID of the user.
        photo_data: Dict with photo metadata (from parse_photo_metadata).

    Returns:
        Saved photo record dict, or None if save failed.

    Raises:
        PhotosError: If save fails.
    """
    photo_data["user_id"] = user_id

    try:
        saved = db_parked.upsert_photo(client, user_id, photo_data)
    except DbError as e:
        raise PhotosError(f"Failed to save photo metadata: {e}") from e

    logger.debug(f"Saved photo metadata: {photo_data.get('filename', 'unknown')}")
    return saved


def complete_photo_processing(client: Client, photo_id: str) -> None:
    """Mark photo as processed successfully and clear the lock.

    Args:
        client: The process database.
        photo_id: UUID of photo to mark as processed.

    Raises:
        PhotosError: If update fails.
    """
    try:
        db_parked.complete_photo(client, photo_id)
        logger.info(f"Completed processing photo {photo_id}")
    except Exception as e:
        raise PhotosError(f"Failed to complete photo processing: {e}") from e


def fail_photo_processing(
    client: Client,
    photo_id: str,
    error: str,
) -> None:
    """Mark photo processing as failed.

    If attempts < max_attempts, sets status back to 'pending' for retry
    with exponential backoff. Otherwise, sets status to 'failed' permanently
    (dead letter). The read and the write are one transaction.

    Args:
        client: The process database.
        photo_id: UUID of photo that failed processing.
        error: Error message to store.

    Raises:
        PhotosError: If update fails (including an unknown photo).
    """
    try:
        outcome = db_parked.fail_photo(client, photo_id, error)
    except Exception as e:
        raise PhotosError(f"Failed to mark photo as failed: {e}") from e

    attempts, max_attempts = outcome["attempts"], outcome["max_attempts"]
    if outcome["should_retry"]:
        logger.warning(
            f"Photo {photo_id} processing failed "
            f"(attempt {attempts}/{max_attempts}): {error}. "
            f"Will retry in {outcome['delay_seconds']}s."
        )
    else:
        logger.error(
            f"Photo {photo_id} processing failed permanently "
            f"after {attempts} attempts: {error}. "
            f"Moved to dead letter."
        )


def get_photo(
    client: Client, photo_id: str, user_id: Optional[str] = None
) -> Optional[dict[str, Any]]:
    """Get one of the user's photo records by ID.

    Args:
        client: The process database.
        photo_id: UUID of the photo.
        user_id: The owning user (required).

    Returns:
        Photo dict, or None if not found (another user's photo is not found).

    Raises:
        PhotosError: If user_id is missing or the query fails.
    """
    if not user_id:
        raise PhotosError("Failed to get photo: user_id is required")
    try:
        return db_parked.get_photo(client, user_id, photo_id)
    except Exception as e:
        raise PhotosError(f"Failed to get photo: {e}") from e


async def unlock_expired_photo_locks(pool) -> int:
    """Reset expired photo locks back to pending.

    Handles the case where a worker crashes mid-processing and the lock expires.

    Args:
        pool: The process database.

    Returns:
        Number of photos unlocked.

    Raises:
        PhotosError: If unlock fails.
    """
    try:
        count = await pool.run(db_parked.unlock_expired_photo_locks, pool)

        if count:
            logger.warning(f"Unlocked {count} expired photo locks")

        return count or 0

    except Exception as e:
        raise PhotosError(f"Failed to unlock expired photo locks: {e}") from e
