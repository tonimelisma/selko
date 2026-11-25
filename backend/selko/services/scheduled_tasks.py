"""Scheduled tasks service for periodic background operations.

This service handles only periodic/scheduled tasks (currently photo_fetch,
parked with Google Photos). Data processing tasks (email_process,
calendar_sync) use status-based claiming directly from their respective data
tables, and email discovery is owned by the ingestion coordinator's own leases
rather than scheduled tasks.

The claim, complete, fail and cleanup operations had no caller and were not
ported to SQLite (docs/specs/sqlite-single-process/02-data-layer.md §2.12,
§3.12); the parked feature ports them when it is revived.
"""

import logging
from datetime import datetime
from typing import Any, Optional

from selko.db import parked as db_parked
from selko.db.connection import Database

Client = Database

logger = logging.getLogger(__name__)


class ScheduledTasksError(Exception):
    """Raised when scheduled task operations fail."""

    pass


def enqueue_scheduled_task(
    client: Client,
    user_id: str,
    task_type: str,
    payload: dict[str, Any],
    scheduled_at: Optional[datetime] = None,
) -> str:
    """Enqueue a new scheduled task.

    Args:
        client: The process database.
        user_id: UUID of user who owns this task.
        task_type: Type of task (currently only 'photo_fetch').
        payload: Task-specific data (e.g., {max_emails: 50}).
        scheduled_at: When to process task (default: now).

    Returns:
        UUID of created task.

    Raises:
        ScheduledTasksError: If task creation fails.
    """
    try:
        task_id = db_parked.enqueue_task(client, user_id, task_type, payload, scheduled_at)
        logger.info(f"Enqueued scheduled task {task_id}: {task_type} for user {user_id}")
        return task_id

    except Exception as e:
        raise ScheduledTasksError(f"Failed to enqueue scheduled task: {e}") from e


async def unlock_expired_scheduled_tasks(pool) -> int:
    """Reset expired scheduled task locks back to pending.

    Handles the case where a worker crashes mid-task and the lock expires.

    Args:
        pool: The process database.

    Returns:
        Number of tasks unlocked.

    Raises:
        ScheduledTasksError: If unlock fails.
    """
    try:
        count = await pool.run(db_parked.unlock_expired_scheduled_tasks, pool)

        if count:
            logger.warning(f"Unlocked {count} expired scheduled task locks")

        return count or 0

    except Exception as e:
        raise ScheduledTasksError(f"Failed to unlock expired scheduled tasks: {e}") from e
