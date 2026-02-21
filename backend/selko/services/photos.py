"""Photos service for Selko.

Handles photo data operations: saving metadata, claiming for processing,
and updating processing status.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from supabase import Client, PostgrestAPIError

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
        client: Authenticated Supabase client.
        user_id: UUID of the user.
        photo_data: Dict with photo metadata (from parse_photo_metadata).

    Returns:
        Saved photo record dict, or None if save failed.

    Raises:
        PhotosError: If save fails.
    """
    photo_data["user_id"] = user_id

    try:
        result = client.table("photos").upsert(
            photo_data, on_conflict="user_id,google_photo_id"
        ).execute()

        if result.data:
            logger.debug(
                f"Saved photo metadata: {photo_data.get('filename', 'unknown')}"
            )
            return result.data[0]

        return None

    except PostgrestAPIError as e:
        raise PhotosError(f"Failed to save photo metadata: {e.message}") from e


def claim_pending_photo(
    client: Client,
    worker_id: str,
    lock_duration_seconds: int = 300,
) -> Optional[dict[str, Any]]:
    """Atomically claim the next pending photo for processing.

    Uses PostgreSQL FOR UPDATE SKIP LOCKED via RPC to safely claim photos
    without conflicts between multiple workers.

    Args:
        client: Authenticated Supabase client (should use service role).
        worker_id: Unique identifier for this worker process.
        lock_duration_seconds: How long to hold the lock (default: 5 minutes).

    Returns:
        Photo dict if claimed, None if no pending photos available.

    Raises:
        PhotosError: If claim operation fails.
    """
    try:
        result = client.rpc("claim_pending_photo", {
            "p_worker_id": worker_id,
            "p_lock_duration_seconds": lock_duration_seconds,
        }).execute()

        if result.data and len(result.data) > 0:
            photo = result.data[0]
            filename = photo.get("filename", "(unknown)")[:50]
            logger.info(
                f"Worker {worker_id} claimed photo {photo['id']}: {filename} "
                f"(attempt {photo['attempts']}/{photo['max_attempts']})"
            )
            return photo

        return None

    except Exception as e:
        raise PhotosError(f"Failed to claim pending photo: {e}") from e


def complete_photo_processing(client: Client, photo_id: str) -> None:
    """Mark photo as processed successfully and clear the lock.

    Args:
        client: Authenticated Supabase client (should use service role).
        photo_id: UUID of photo to mark as processed.

    Raises:
        PhotosError: If update fails.
    """
    try:
        client.table("photos").update({
            "processing_status": "processed",
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "locked_by": None,
            "locked_until": None,
        }).eq("id", photo_id).execute()

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
    (dead letter).

    Args:
        client: Authenticated Supabase client (should use service role).
        photo_id: UUID of photo that failed processing.
        error: Error message to store.

    Raises:
        PhotosError: If update fails.
    """
    try:
        # Fetch current photo to check retry eligibility
        result = client.table("photos").select(
            "attempts, max_attempts"
        ).eq("id", photo_id).single().execute()

        photo = result.data
        attempts = photo["attempts"]
        max_attempts = photo["max_attempts"]
        should_retry = attempts < max_attempts

        update_data: dict[str, Any] = {
            "processing_status": "pending" if should_retry else "failed",
            "processing_error": error,
            "locked_by": None,
            "locked_until": None,
        }

        if should_retry:
            # Exponential backoff: 60s, 120s, 240s, ... capped at 3600s
            base_delay = 60  # seconds
            max_delay = 3600  # 1 hour
            delay = min(base_delay * (2 ** (attempts - 1)), max_delay)
            next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            update_data["next_retry_at"] = next_retry_at.isoformat()
        else:
            # Dead letter: permanently failed
            update_data["dead_letter_reason"] = error
            update_data["dead_letter_at"] = datetime.now(timezone.utc).isoformat()

        client.table("photos").update(update_data).eq("id", photo_id).execute()

        if should_retry:
            logger.warning(
                f"Photo {photo_id} processing failed "
                f"(attempt {attempts}/{max_attempts}): {error}. "
                f"Will retry in {delay}s."
            )
        else:
            logger.error(
                f"Photo {photo_id} processing failed permanently "
                f"after {attempts} attempts: {error}. "
                f"Moved to dead letter."
            )

    except Exception as e:
        raise PhotosError(f"Failed to mark photo as failed: {e}") from e


def get_photo(client: Client, photo_id: str) -> Optional[dict[str, Any]]:
    """Get a single photo record by ID.

    Args:
        client: Authenticated Supabase client.
        photo_id: UUID of the photo.

    Returns:
        Photo dict, or None if not found.

    Raises:
        PhotosError: If query fails.
    """
    try:
        result = client.table("photos").select("*").eq(
            "id", photo_id
        ).maybe_single().execute()

        if result is None or not result.data:
            return None

        return result.data

    except Exception as e:
        raise PhotosError(f"Failed to get photo: {e}") from e


def unlock_expired_photo_locks(client: Client) -> int:
    """Reset expired photo locks back to pending.

    Handles the case where a worker crashes mid-processing and the lock expires.

    Args:
        client: Authenticated Supabase client (should use service role).

    Returns:
        Number of photos unlocked.

    Raises:
        PhotosError: If unlock fails.
    """
    try:
        result = client.rpc("unlock_expired_photo_locks").execute()
        count = result.data if result.data else 0

        if count > 0:
            logger.warning(f"Unlocked {count} expired photo locks")

        return count

    except Exception as e:
        raise PhotosError(f"Failed to unlock expired photo locks: {e}") from e
