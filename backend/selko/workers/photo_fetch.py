"""Photo fetch worker - fetches photos from Google Photos.

This worker:
1. Fetches recent photos from Google Photos for a user
2. Stores metadata in the photos table with processing_status='pending'

Photos are automatically picked up by the worker pool for LLM processing
because they're saved with processing_status='pending'.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from supabase import Client

from selko.config import Config
from selko.services.google_photos import (
    PhotosError,
    fetch_recent_photos,
    parse_photo_metadata,
)
from selko.services.photos import save_photo_metadata
from selko.services.scheduled_tasks import enqueue_scheduled_task

logger = logging.getLogger(__name__)


async def process_photo_fetch_task(
    client: Client,
    config: Config,
    payload: dict[str, Any],
) -> None:
    """Process a photo_fetch scheduled task.

    Args:
        client: Supabase client (with service role).
        config: Application configuration.
        payload: Task payload with {user_id: str, max_photos: int}.

    Raises:
        PhotosError: If Google Photos API calls fail.
    """
    user_id = payload.get("user_id")
    max_photos = payload.get("max_photos", 100)

    if not user_id:
        raise ValueError("Missing user_id in payload")

    logger.info(f"Fetching up to {max_photos} photos for user {user_id}")

    # Determine since_date from last sync
    since_date = None
    try:
        integration_result = client.table("integrations").select(
            "last_photo_sync_at"
        ).eq("user_id", user_id).eq("provider", "google_photos").maybe_single().execute()

        if integration_result and integration_result.data:
            last_sync = integration_result.data.get("last_photo_sync_at")
            if last_sync:
                since_date = datetime.fromisoformat(
                    last_sync.replace("Z", "+00:00")
                )
    except Exception as e:
        logger.warning(f"Could not determine last photo sync time: {e}")

    # Fetch photos from Google Photos API
    try:
        media_items = fetch_recent_photos(
            client, config, user_id=user_id,
            since_date=since_date, max_results=max_photos,
        )
    except PhotosError as e:
        logger.error(f"Error fetching photos for user {user_id}: {e}")
        raise

    if not media_items:
        logger.info(f"No new photos found for user {user_id}")
        return

    # Parse and save photo metadata
    # Photos are saved with processing_status='pending' (default)
    # The worker pool will automatically pick them up for LLM processing
    saved_count = 0
    for item in media_items:
        try:
            photo_data = parse_photo_metadata(item)
            result = save_photo_metadata(client, user_id, photo_data)
            if result:
                saved_count += 1
        except Exception as e:
            logger.error(
                f"Failed to save photo {item.get('id', 'unknown')}: {e}"
            )
            continue

    logger.info(
        f"Saved {saved_count} photos for user {user_id} "
        f"(will be auto-processed by workers)"
    )

    # Update last_photo_sync_at
    try:
        client.table("integrations").update({
            "last_photo_sync_at": datetime.now(timezone.utc).isoformat(),
        }).eq("user_id", user_id).eq("provider", "google_photos").execute()
    except Exception as e:
        logger.warning(f"Failed to update last_photo_sync_at: {e}")


async def schedule_photo_fetches() -> None:
    """Scheduler function that creates photo_fetch tasks for all users.

    Called by APScheduler periodically. Creates one photo_fetch scheduled task
    per user who has an active Google Photos integration, skipping users who
    already have a pending or processing task.
    """
    from selko.config import load_config
    from selko.services.auth import get_service_client

    config = load_config()
    client = get_service_client(config)

    try:
        # Get all users with active Google Photos integrations
        result = client.table("integrations").select(
            "user_id"
        ).eq("provider", "google_photos").eq("status", "active").execute()

        users = {row["user_id"] for row in result.data}

        if not users:
            logger.debug("No users with active Google Photos integrations")
            return

        # Find users who already have a pending or processing photo_fetch task
        existing_result = client.table("scheduled_tasks").select(
            "user_id"
        ).eq(
            "task_type", "photo_fetch"
        ).in_(
            "status", ["pending", "processing"]
        ).execute()

        users_with_existing_task = {row["user_id"] for row in existing_result.data}

        # Create photo_fetch scheduled task only for users without an existing one
        tasks_created = 0
        tasks_skipped = 0
        for user_id in users:
            if user_id in users_with_existing_task:
                tasks_skipped += 1
                continue
            try:
                enqueue_scheduled_task(
                    client,
                    user_id=user_id,
                    task_type="photo_fetch",
                    payload={"user_id": user_id, "max_photos": 100},
                )
                tasks_created += 1
            except Exception as e:
                logger.error(f"Failed to enqueue photo_fetch for user {user_id}: {e}")

        if tasks_skipped:
            logger.info(
                f"Scheduled photo fetch for {tasks_created} users "
                f"({tasks_skipped} skipped - already queued)"
            )
        else:
            logger.info(f"Scheduled photo fetch for {tasks_created} users")

    except Exception as e:
        logger.error(f"Failed to schedule photo fetches: {e}", exc_info=True)
