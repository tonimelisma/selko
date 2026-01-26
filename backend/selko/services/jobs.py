"""Job queue service for async background processing.

Implements a PostgreSQL-based job queue using atomic operations and locking
to safely distribute work across multiple workers in the Async Monolith pattern.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from supabase import Client

logger = logging.getLogger(__name__)


class JobsError(Exception):
    """Raised when job operations fail."""

    pass


def enqueue_job(
    client: Client,
    user_id: str,
    job_type: str,
    payload: dict[str, Any],
    priority: int = 0,
    scheduled_at: Optional[datetime] = None,
    max_attempts: int = 3,
) -> str:
    """Enqueue a new job for background processing.

    Args:
        client: Authenticated Supabase client (should use service role).
        user_id: UUID of user who owns this job.
        job_type: Type of job (email_fetch, email_process, calendar_sync).
        payload: Job-specific data (e.g., {email_id: "uuid"}).
        priority: Priority level (higher = more urgent, default 0).
        scheduled_at: When to process job (default: now).
        max_attempts: Maximum retry attempts (default: 3).

    Returns:
        UUID of created job.

    Raises:
        JobsError: If job creation fails.
    """
    try:
        job_data = {
            "user_id": user_id,
            "job_type": job_type,
            "payload": payload,
            "priority": priority,
            "max_attempts": max_attempts,
        }
        
        # Only include scheduled_at if explicitly provided
        # Otherwise let the database default to now()
        if scheduled_at is not None:
            job_data["scheduled_at"] = scheduled_at.isoformat()
        
        result = client.table("jobs").insert(job_data).execute()

        job_id = result.data[0]["id"]
        logger.info(f"Enqueued job {job_id}: {job_type} for user {user_id}")
        return job_id

    except Exception as e:
        raise JobsError(f"Failed to enqueue job: {e}") from e


def claim_job(
    client: Client,
    job_types: list[str],
    worker_id: str,
    lock_duration_seconds: int = 300,
) -> Optional[dict[str, Any]]:
    """Atomically claim the next pending job.

    Uses PostgreSQL FOR UPDATE SKIP LOCKED to safely claim jobs without
    conflicts between multiple workers.

    Args:
        client: Authenticated Supabase client (should use service role).
        job_types: List of job types this worker can handle.
        worker_id: Unique identifier for this worker process.
        lock_duration_seconds: How long to hold the lock (default: 5 minutes).

    Returns:
        Job dict if claimed, None if no jobs available.

    Raises:
        JobsError: If claim operation fails.
    """
    try:
        result = client.rpc('claim_next_job', {
            'p_job_types': job_types,
            'p_worker_id': worker_id,
            'p_lock_duration_seconds': lock_duration_seconds,
        }).execute()

        if result.data and len(result.data) > 0:
            job = result.data[0]
            logger.info(
                f"Worker {worker_id} claimed job {job['id']}: "
                f"{job['job_type']} (attempt {job['attempts']}/{job['max_attempts']})"
            )
            return job

        return None

    except Exception as e:
        raise JobsError(f"Failed to claim job: {e}") from e


def complete_job(client: Client, job_id: str) -> None:
    """Mark job as completed successfully.

    Args:
        client: Authenticated Supabase client (should use service role).
        job_id: UUID of job to complete.

    Raises:
        JobsError: If update fails.
    """
    try:
        client.table("jobs").update({
            "status": "completed",
            "completed_at": datetime.now().isoformat(),
            "locked_by": None,
            "locked_until": None,
        }).eq("id", job_id).execute()

        logger.info(f"Completed job {job_id}")

    except Exception as e:
        raise JobsError(f"Failed to complete job: {e}") from e


def fail_job(
    client: Client,
    job_id: str,
    error: str,
    retry: bool = True,
) -> None:
    """Mark job as failed and optionally retry.

    Args:
        client: Authenticated Supabase client (should use service role).
        job_id: UUID of job that failed.
        error: Error message to store.
        retry: If True, will retry if attempts < max_attempts.

    Raises:
        JobsError: If update fails.
    """
    try:
        # Fetch current job to check retry eligibility
        result = client.table("jobs").select("attempts, max_attempts").eq(
            "id", job_id
        ).single().execute()

        job = result.data
        should_retry = retry and job["attempts"] < job["max_attempts"]

        update_data = {
            "status": "pending" if should_retry else "dead",
            "last_error": error,
            "locked_by": None,
            "locked_until": None,
        }

        if not should_retry:
            update_data["completed_at"] = datetime.now().isoformat()

        client.table("jobs").update(update_data).eq("id", job_id).execute()

        if should_retry:
            logger.warning(
                f"Job {job_id} failed (attempt {job['attempts']}/{job['max_attempts']}): "
                f"{error}. Will retry."
            )
        else:
            logger.error(
                f"Job {job_id} failed permanently after {job['attempts']} attempts: {error}"
            )

    except Exception as e:
        raise JobsError(f"Failed to update failed job: {e}") from e


def get_pending_count(client: Client, user_id: Optional[str] = None) -> dict[str, int]:
    """Get count of pending jobs by type.

    Args:
        client: Authenticated Supabase client.
        user_id: Optional user ID to filter by.

    Returns:
        Dict mapping job_type to count of pending jobs.

    Raises:
        JobsError: If query fails.
    """
    try:
        query = client.table("jobs").select(
            "job_type", count="exact"
        ).eq("status", "pending")

        if user_id:
            query = query.eq("user_id", user_id)

        result = query.execute()

        # Group by job_type
        counts: dict[str, int] = {}
        for row in result.data:
            job_type = row["job_type"]
            counts[job_type] = counts.get(job_type, 0) + 1

        return counts

    except Exception as e:
        raise JobsError(f"Failed to get pending count: {e}") from e


def get_job_status(client: Client, job_id: str) -> dict[str, Any]:
    """Get status of a specific job.

    Args:
        client: Authenticated Supabase client.
        job_id: UUID of job to query.

    Returns:
        Job dict with status info.

    Raises:
        JobsError: If job not found or query fails.
    """
    try:
        result = client.table("jobs").select("*").eq("id", job_id).single().execute()
        return result.data

    except Exception as e:
        raise JobsError(f"Failed to get job status: {e}") from e


def cleanup_old_jobs(
    client: Client,
    days_old: int = 7,
    status_filter: Optional[list[str]] = None,
) -> int:
    """Delete old completed/failed jobs for cleanup.

    Args:
        client: Authenticated Supabase client (should use service role).
        days_old: Delete jobs older than this many days.
        status_filter: Only delete jobs with these statuses (default: completed, dead).

    Returns:
        Number of jobs deleted.

    Raises:
        JobsError: If cleanup fails.
    """
    if status_filter is None:
        status_filter = ["completed", "dead"]

    try:
        cutoff_date = datetime.now() - timedelta(days=days_old)

        result = client.table("jobs").delete().in_(
            "status", status_filter
        ).lt("completed_at", cutoff_date.isoformat()).execute()

        count = len(result.data) if result.data else 0
        logger.info(f"Cleaned up {count} old jobs (>{days_old} days)")
        return count

    except Exception as e:
        raise JobsError(f"Failed to cleanup jobs: {e}") from e


def unlock_expired_jobs(client: Client) -> int:
    """Reset expired job locks back to pending.

    Handles the case where a worker crashes mid-job and the lock expires.

    Args:
        client: Authenticated Supabase client (should use service role).

    Returns:
        Number of jobs unlocked.

    Raises:
        JobsError: If unlock fails.
    """
    try:
        result = client.rpc('unlock_expired_jobs').execute()
        count = result.data if result.data else 0

        if count > 0:
            logger.warning(f"Unlocked {count} expired job locks")

        return count

    except Exception as e:
        raise JobsError(f"Failed to unlock expired jobs: {e}") from e
