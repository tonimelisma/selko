"""Integration tests for job queue system.

Tests the PostgreSQL-based job queue using real Supabase database.
"""

import logging
from datetime import datetime, timedelta, timezone

import pytest
from supabase import Client

from selko.config import Config
from selko.services.auth import get_service_client
from selko.services.jobs import (
    JobsError,
    cleanup_old_jobs,
    claim_job,
    complete_job,
    enqueue_job,
    fail_job,
    get_job_status,
    get_pending_count,
    unlock_expired_jobs,
)

logger = logging.getLogger(__name__)


@pytest.fixture
def service_client(config: Config) -> Client:
    """Get a service role client for testing job operations."""
    return get_service_client(config)


@pytest.fixture(autouse=True)
def cleanup_jobs(service_client: Client, test_user_id: str):
    """Clean up all jobs for the test user before each test."""
    # Delete all jobs for this user before the test runs
    try:
        service_client.table("jobs").delete().eq("user_id", test_user_id).execute()
    except Exception as e:
        logger.warning(f"Failed to cleanup jobs: {e}")
    
    yield
    
    # Clean up after test completes
    try:
        service_client.table("jobs").delete().eq("user_id", test_user_id).execute()
    except Exception as e:
        logger.warning(f"Failed to cleanup jobs after test: {e}")


@pytest.mark.integration
@pytest.mark.development
def test_enqueue_and_claim_job(service_client: Client, test_user_id: str):
    """Test basic job enqueue and claim operations."""
    # Enqueue a job
    job_id = enqueue_job(
        service_client,
        user_id=test_user_id,
        job_type="email_fetch",
        payload={"max_emails": 50},
        priority=0,
    )

    assert job_id is not None

    # Claim the job
    worker_id = "test-worker-1"
    claimed_job = claim_job(
        service_client,
        job_types=["email_fetch"],
        worker_id=worker_id,
    )

    assert claimed_job is not None
    assert claimed_job["id"] == job_id
    assert claimed_job["status"] == "processing"
    assert claimed_job["locked_by"] == worker_id
    assert claimed_job["attempts"] == 1


@pytest.mark.integration
@pytest.mark.development
def test_complete_job(service_client: Client, test_user_id: str):
    """Test marking a job as completed."""
    # Enqueue and claim a job
    job_id = enqueue_job(
        service_client,
        user_id=test_user_id,
        job_type="email_process",
        payload={"email_id": "test-uuid"},
    )

    claimed_job = claim_job(
        service_client,
        job_types=["email_process"],
        worker_id="test-worker",
    )

    # Complete the job
    complete_job(service_client, job_id)

    # Verify status
    job = get_job_status(service_client, job_id)
    assert job["status"] == "completed"
    assert job["completed_at"] is not None
    assert job["locked_by"] is None


@pytest.mark.integration
@pytest.mark.development
def test_fail_job_with_retry(service_client: Client, test_user_id: str):
    """Test failing a job with retry logic."""
    # Enqueue a job with max_attempts=2
    job_id = enqueue_job(
        service_client,
        user_id=test_user_id,
        job_type="calendar_sync",
        payload={"event_id": "test-uuid"},
        max_attempts=2,
    )

    # Claim and fail the job (first attempt)
    claim_job(service_client, ["calendar_sync"], "worker-1")
    fail_job(service_client, job_id, "Test error", retry=True)

    # Should be back to pending for retry
    job = get_job_status(service_client, job_id)
    assert job["status"] == "pending"
    assert job["attempts"] == 1
    assert job["last_error"] == "Test error"

    # Claim and fail again (second attempt - should go to dead)
    claim_job(service_client, ["calendar_sync"], "worker-2")
    fail_job(service_client, job_id, "Test error again", retry=True)

    # Should be dead now (exceeded max_attempts)
    job = get_job_status(service_client, job_id)
    assert job["status"] == "dead"
    assert job["attempts"] == 2


@pytest.mark.integration
@pytest.mark.development
def test_job_priority_ordering(service_client: Client, test_user_id: str):
    """Test that higher priority jobs are claimed first."""
    # Enqueue jobs with different priorities
    low_priority_id = enqueue_job(
        service_client,
        user_id=test_user_id,
        job_type="email_fetch",
        payload={"priority": "low"},
        priority=0,
    )

    high_priority_id = enqueue_job(
        service_client,
        user_id=test_user_id,
        job_type="email_fetch",
        payload={"priority": "high"},
        priority=10,
    )

    # Claim a job - should get high priority first
    claimed = claim_job(service_client, ["email_fetch"], "worker-1")

    assert claimed["id"] == high_priority_id
    assert claimed["priority"] == 10


@pytest.mark.integration
@pytest.mark.development
def test_get_pending_count(service_client: Client, test_user_id: str):
    """Test getting count of pending jobs by type."""
    # Enqueue multiple jobs of different types
    enqueue_job(
        service_client,
        user_id=test_user_id,
        job_type="email_fetch",
        payload={},
    )
    enqueue_job(
        service_client,
        user_id=test_user_id,
        job_type="email_fetch",
        payload={},
    )
    enqueue_job(
        service_client,
        user_id=test_user_id,
        job_type="email_process",
        payload={},
    )

    # Get counts
    counts = get_pending_count(service_client, user_id=test_user_id)

    assert counts.get("email_fetch", 0) >= 2
    assert counts.get("email_process", 0) >= 1


@pytest.mark.integration
@pytest.mark.development
def test_skip_locked_concurrent_claims(service_client: Client, test_user_id: str):
    """Test that SKIP LOCKED prevents concurrent workers from claiming same job."""
    # Enqueue a single job
    job_id = enqueue_job(
        service_client,
        user_id=test_user_id,
        job_type="email_fetch",
        payload={},
    )

    # Worker 1 claims it
    claimed_1 = claim_job(service_client, ["email_fetch"], "worker-1")
    assert claimed_1["id"] == job_id

    # Worker 2 tries to claim - should get None (no available jobs)
    claimed_2 = claim_job(service_client, ["email_fetch"], "worker-2")
    assert claimed_2 is None


@pytest.mark.integration
@pytest.mark.development
def test_unlock_expired_jobs(service_client: Client, test_user_id: str):
    """Test unlocking jobs that exceeded their lock duration."""
    # Enqueue and claim a job
    job_id = enqueue_job(
        service_client,
        user_id=test_user_id,
        job_type="email_fetch",
        payload={},
    )

    claim_job(
        service_client,
        ["email_fetch"],
        "worker-1",
        lock_duration_seconds=1,  # Very short lock for testing
    )

    # Wait for lock to expire
    import time
    time.sleep(2)

    # Unlock expired jobs
    count = unlock_expired_jobs(service_client)

    assert count >= 1

    # Should be able to claim it again now
    claimed = claim_job(service_client, ["email_fetch"], "worker-2")
    assert claimed is not None
    assert claimed["id"] == job_id


@pytest.mark.integration
@pytest.mark.development
def test_cleanup_old_jobs(service_client: Client, test_user_id: str):
    """Test cleaning up old completed/failed jobs."""
    # Enqueue, claim, and complete a job
    job_id = enqueue_job(
        service_client,
        user_id=test_user_id,
        job_type="email_fetch",
        payload={},
    )

    claim_job(service_client, ["email_fetch"], "worker-1")
    complete_job(service_client, job_id)

    # Manually update completed_at to be old (8 days ago)
    old_date = (datetime.now() - timedelta(days=8)).isoformat()
    service_client.table("jobs").update({
        "completed_at": old_date
    }).eq("id", job_id).execute()

    # Cleanup jobs older than 7 days
    count = cleanup_old_jobs(service_client, days_old=7)

    assert count >= 1

    # Job should be deleted
    with pytest.raises(JobsError):
        get_job_status(service_client, job_id)


@pytest.mark.integration
@pytest.mark.development
def test_scheduled_job_future_execution(service_client: Client, test_user_id: str):
    """Test that jobs scheduled in the future are not claimed yet."""
    # Enqueue a job scheduled 1 hour in the future
    future_time = datetime.now(timezone.utc) + timedelta(hours=1)
    job_id = enqueue_job(
        service_client,
        user_id=test_user_id,
        job_type="email_fetch",
        payload={},
        scheduled_at=future_time,
    )

    # Try to claim - should get None (not ready yet)
    claimed = claim_job(service_client, ["email_fetch"], "worker-1")

    # The future job should not be claimed
    assert claimed is None
