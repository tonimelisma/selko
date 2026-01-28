"""Scheduled tasks service for periodic background operations.

This service handles only periodic/scheduled tasks (like email_fetch).
Data processing tasks (email_process, calendar_sync) use status-based
claiming directly from their respective data tables.
"""

import logging
from datetime import datetime
from typing import Any, Optional

from supabase import Client

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
        client: Authenticated Supabase client (should use service role).
        user_id: UUID of user who owns this task.
        task_type: Type of task (currently only 'email_fetch').
        payload: Task-specific data (e.g., {max_emails: 50}).
        scheduled_at: When to process task (default: now).

    Returns:
        UUID of created task.

    Raises:
        ScheduledTasksError: If task creation fails.
    """
    try:
        task_data = {
            "user_id": user_id,
            "task_type": task_type,
            "payload": payload,
        }

        if scheduled_at is not None:
            task_data["scheduled_at"] = scheduled_at.isoformat()

        result = client.table("scheduled_tasks").insert(task_data).execute()

        task_id = result.data[0]["id"]
        logger.info(f"Enqueued scheduled task {task_id}: {task_type} for user {user_id}")
        return task_id

    except Exception as e:
        raise ScheduledTasksError(f"Failed to enqueue scheduled task: {e}") from e


def claim_scheduled_task(
    client: Client,
    task_types: list[str],
    worker_id: str,
    lock_duration_seconds: int = 300,
) -> Optional[dict[str, Any]]:
    """Atomically claim the next pending scheduled task.

    Uses PostgreSQL FOR UPDATE SKIP LOCKED to safely claim tasks without
    conflicts between multiple workers.

    Args:
        client: Authenticated Supabase client (should use service role).
        task_types: List of task types this worker can handle.
        worker_id: Unique identifier for this worker process.
        lock_duration_seconds: How long to hold the lock (default: 5 minutes).

    Returns:
        Task dict if claimed, None if no tasks available.

    Raises:
        ScheduledTasksError: If claim operation fails.
    """
    try:
        result = client.rpc('claim_next_scheduled_task', {
            'p_task_types': task_types,
            'p_worker_id': worker_id,
            'p_lock_duration_seconds': lock_duration_seconds,
        }).execute()

        if result.data and len(result.data) > 0:
            task = result.data[0]
            logger.info(
                f"Worker {worker_id} claimed scheduled task {task['id']}: {task['task_type']}"
            )
            return task

        return None

    except Exception as e:
        raise ScheduledTasksError(f"Failed to claim scheduled task: {e}") from e


def complete_scheduled_task(client: Client, task_id: str) -> None:
    """Mark scheduled task as completed successfully.

    Args:
        client: Authenticated Supabase client (should use service role).
        task_id: UUID of task to complete.

    Raises:
        ScheduledTasksError: If update fails.
    """
    try:
        client.table("scheduled_tasks").update({
            "status": "completed",
            "completed_at": datetime.now().isoformat(),
            "locked_by": None,
            "locked_until": None,
        }).eq("id", task_id).execute()

        logger.info(f"Completed scheduled task {task_id}")

    except Exception as e:
        raise ScheduledTasksError(f"Failed to complete scheduled task: {e}") from e


def fail_scheduled_task(
    client: Client,
    task_id: str,
    error: str,
) -> None:
    """Mark scheduled task as failed.

    Scheduled tasks don't retry - they will be re-enqueued by the scheduler.

    Args:
        client: Authenticated Supabase client (should use service role).
        task_id: UUID of task that failed.
        error: Error message to store.

    Raises:
        ScheduledTasksError: If update fails.
    """
    try:
        client.table("scheduled_tasks").update({
            "status": "failed",
            "last_error": error,
            "completed_at": datetime.now().isoformat(),
            "locked_by": None,
            "locked_until": None,
        }).eq("id", task_id).execute()

        logger.error(f"Scheduled task {task_id} failed: {error}")

    except Exception as e:
        raise ScheduledTasksError(f"Failed to update failed scheduled task: {e}") from e


def unlock_expired_scheduled_tasks(client: Client) -> int:
    """Reset expired scheduled task locks back to pending.

    Handles the case where a worker crashes mid-task and the lock expires.

    Args:
        client: Authenticated Supabase client (should use service role).

    Returns:
        Number of tasks unlocked.

    Raises:
        ScheduledTasksError: If unlock fails.
    """
    try:
        result = client.rpc('unlock_expired_scheduled_tasks').execute()
        count = result.data if result.data else 0

        if count > 0:
            logger.warning(f"Unlocked {count} expired scheduled task locks")

        return count

    except Exception as e:
        raise ScheduledTasksError(f"Failed to unlock expired scheduled tasks: {e}") from e


def cleanup_old_scheduled_tasks(
    client: Client,
    days_old: int = 7,
) -> int:
    """Delete old completed/failed scheduled tasks for cleanup.

    Args:
        client: Authenticated Supabase client (should use service role).
        days_old: Delete tasks older than this many days.

    Returns:
        Number of tasks deleted.

    Raises:
        ScheduledTasksError: If cleanup fails.
    """
    from datetime import timedelta

    try:
        cutoff_date = datetime.now() - timedelta(days=days_old)

        result = client.table("scheduled_tasks").delete().in_(
            "status", ["completed", "failed"]
        ).lt("completed_at", cutoff_date.isoformat()).execute()

        count = len(result.data) if result.data else 0
        logger.info(f"Cleaned up {count} old scheduled tasks (>{days_old} days)")
        return count

    except Exception as e:
        raise ScheduledTasksError(f"Failed to cleanup scheduled tasks: {e}") from e
