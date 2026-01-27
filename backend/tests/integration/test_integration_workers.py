"""Integration tests for worker job processing.

Tests the worker job handlers with real Supabase database but mocked
external APIs (Gmail, Google Calendar, Gemini).
"""

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from supabase import Client

from selko.config import Config
from selko.services.auth import get_service_client
from selko.services.jobs import (
    claim_job,
    complete_job,
    enqueue_job,
    fail_job,
    get_job_status,
)

logger = logging.getLogger(__name__)


@pytest.fixture
def service_client(config: Config) -> Client:
    """Get a service role client for testing job operations."""
    return get_service_client(config)


@pytest.fixture(autouse=True)
def cleanup_jobs_and_data(service_client: Client, test_user_id: str):
    """Clean up all test data before and after each test."""
    # Delete all jobs for this user before the test
    try:
        service_client.table("jobs").delete().eq("user_id", test_user_id).execute()
    except Exception as e:
        logger.warning(f"Failed to cleanup jobs: {e}")

    yield

    # Clean up after test
    try:
        service_client.table("jobs").delete().eq("user_id", test_user_id).execute()
    except Exception as e:
        logger.warning(f"Failed to cleanup jobs after test: {e}")


@pytest.mark.integration
@pytest.mark.development
class TestCalendarSyncWorker:
    """Tests for calendar_sync worker job handler."""

    @pytest.mark.asyncio
    async def test_processes_approved_event(
        self, service_client, authenticated_client, test_user_id, config
    ):
        """Test that calendar_sync worker processes an approved event."""
        from selko.workers.calendar_sync import process_calendar_sync_job

        # Create an approved event
        event_data = {
            "user_id": test_user_id,
            "title": "Worker Test Event",
            "start_datetime": "2026-05-01T14:00:00Z",
            "end_datetime": "2026-05-01T15:00:00Z",
            "status": "approved",
        }

        result = authenticated_client.table("events").insert(event_data).execute()
        event_id = result.data[0]["id"]

        # Enqueue calendar_sync job
        job_id = enqueue_job(
            service_client,
            user_id=test_user_id,
            job_type="calendar_sync",
            payload={"event_id": event_id},
        )

        # Mock Google Calendar API
        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()

            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.insert.return_value.execute.return_value = {
                "id": "google-worker-test-123"
            }

            # Process the job
            await process_calendar_sync_job(
                service_client, config, job_id, {"event_id": event_id}
            )

        # Verify event was synced
        updated_event = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()

        assert updated_event.data["status"] == "synced"
        assert updated_event.data["google_calendar_event_id"] == "google-worker-test-123"

    @pytest.mark.asyncio
    async def test_skips_non_approved_event(
        self, service_client, authenticated_client, test_user_id, config
    ):
        """Test that calendar_sync worker skips non-approved events."""
        from selko.workers.calendar_sync import process_calendar_sync_job

        # Create a pending (not approved) event
        event_data = {
            "user_id": test_user_id,
            "title": "Pending Event",
            "start_datetime": "2026-05-02T14:00:00Z",
            "status": "pending_review",  # Not approved
        }

        result = authenticated_client.table("events").insert(event_data).execute()
        event_id = result.data[0]["id"]

        # Process the job - should not call Google API
        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()
            mock_service = MagicMock()
            mock_build.return_value = mock_service

            await process_calendar_sync_job(
                service_client, config, "job-123", {"event_id": event_id}
            )

            # Should not have called insert
            mock_service.events.return_value.insert.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_error_for_missing_event_id(
        self, service_client, config
    ):
        """Test that calendar_sync worker raises error for missing event_id."""
        from selko.workers.calendar_sync import process_calendar_sync_job

        with pytest.raises(ValueError) as exc_info:
            await process_calendar_sync_job(
                service_client, config, "job-123", {}  # Missing event_id
            )

        assert "Missing event_id" in str(exc_info.value)


@pytest.mark.integration
@pytest.mark.development
class TestEmailProcessWorker:
    """Tests for email_process worker job handler."""

    @pytest.mark.asyncio
    async def test_processes_email_for_events(
        self, service_client, authenticated_client, test_user_id, config, mock_gemini_client
    ):
        """Test that email_process worker extracts events from email."""
        from selko.workers.email_process import process_email_process_job

        # Create a test email
        email_data = {
            "user_id": test_user_id,
            "gmail_id": f"worker-test-{uuid4().hex[:8]}",
            "subject": "Birthday Party Invitation",
            "from_email": "friend@example.com",
            "from_name": "Best Friend",
            "date_sent": "2026-05-15T12:00:00Z",
            "snippet": "You're invited to Jake's birthday party on May 20th at 2pm!",
            "gmail_label_ids": ["INBOX"],
            "processing_status": "pending",
        }

        result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = result.data[0]["id"]

        # Process with mocked Gemini
        with patch("selko.workers.email_process.get_gemini_client") as mock_get_gemini:
            mock_get_gemini.return_value = mock_gemini_client

            await process_email_process_job(
                service_client, config, "job-456", {"email_id": email_id}
            )

        # Verify email was processed
        updated_email = authenticated_client.table("emails").select("*").eq(
            "id", email_id
        ).single().execute()

        assert updated_email.data["processing_status"] == "processed"

    @pytest.mark.asyncio
    async def test_marks_email_failed_on_error(
        self, service_client, authenticated_client, test_user_id, config
    ):
        """Test that email_process marks email as failed on processing error."""
        from selko.workers.email_process import process_email_process_job

        # Create a test email
        email_data = {
            "user_id": test_user_id,
            "gmail_id": f"worker-fail-{uuid4().hex[:8]}",
            "subject": "Test Email",
            "from_email": "test@example.com",
            "date_sent": "2026-05-15T12:00:00Z",
            "snippet": "Test content",
            "gmail_label_ids": ["INBOX"],
            "processing_status": "pending",
        }

        result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = result.data[0]["id"]

        # Process with Gemini that fails
        with patch("selko.workers.email_process.get_gemini_client") as mock_get_gemini:
            mock_client = MagicMock()
            mock_client.models.generate_content.side_effect = Exception("Gemini API Error")
            mock_get_gemini.return_value = mock_client

            with pytest.raises(Exception):
                await process_email_process_job(
                    service_client, config, "job-789", {"email_id": email_id}
                )

        # Verify email was marked as failed
        updated_email = authenticated_client.table("emails").select("*").eq(
            "id", email_id
        ).single().execute()

        assert updated_email.data["processing_status"] == "failed"


@pytest.mark.integration
@pytest.mark.development
class TestWorkerJobLifecycle:
    """Tests for complete job lifecycle through workers."""

    def test_job_claim_updates_status(self, service_client, test_user_id):
        """Test that claiming a job properly updates its status."""
        # Enqueue a job
        job_id = enqueue_job(
            service_client,
            user_id=test_user_id,
            job_type="email_fetch",
            payload={"max_emails": 10},
        )

        # Verify initial status
        job = get_job_status(service_client, job_id)
        assert job["status"] == "pending"
        assert job["locked_by"] is None

        # Claim the job
        claimed = claim_job(service_client, ["email_fetch"], "test-worker")

        # Verify claimed status
        job = get_job_status(service_client, job_id)
        assert job["status"] == "processing"
        assert job["locked_by"] == "test-worker"
        assert job["attempts"] == 1

    def test_job_completion_clears_lock(self, service_client, test_user_id):
        """Test that completing a job clears the lock."""
        # Enqueue and claim
        job_id = enqueue_job(
            service_client,
            user_id=test_user_id,
            job_type="email_fetch",
            payload={},
        )
        claim_job(service_client, ["email_fetch"], "test-worker")

        # Complete
        complete_job(service_client, job_id)

        # Verify
        job = get_job_status(service_client, job_id)
        assert job["status"] == "completed"
        assert job["locked_by"] is None
        assert job["completed_at"] is not None

    def test_job_failure_with_retry_resets_status(self, service_client, test_user_id):
        """Test that failing a job with retry resets it to pending."""
        # Enqueue with multiple attempts allowed
        job_id = enqueue_job(
            service_client,
            user_id=test_user_id,
            job_type="email_process",
            payload={},
            max_attempts=3,
        )
        claim_job(service_client, ["email_process"], "test-worker")

        # Fail with retry
        fail_job(service_client, job_id, "Temporary error", retry=True)

        # Verify
        job = get_job_status(service_client, job_id)
        assert job["status"] == "pending"
        assert job["locked_by"] is None
        assert job["last_error"] == "Temporary error"
        assert job["attempts"] == 1

    def test_job_failure_exceeds_max_attempts(self, service_client, test_user_id):
        """Test that job goes to dead status after exceeding max attempts."""
        # Enqueue with only 1 attempt
        job_id = enqueue_job(
            service_client,
            user_id=test_user_id,
            job_type="calendar_sync",
            payload={},
            max_attempts=1,
        )

        # Claim and fail
        claim_job(service_client, ["calendar_sync"], "test-worker")
        fail_job(service_client, job_id, "Fatal error", retry=True)

        # Verify job is dead
        job = get_job_status(service_client, job_id)
        assert job["status"] == "dead"
        assert job["attempts"] == 1

    def test_job_failure_without_retry_goes_dead(self, service_client, test_user_id):
        """Test that failing without retry immediately goes to dead."""
        job_id = enqueue_job(
            service_client,
            user_id=test_user_id,
            job_type="email_fetch",
            payload={},
            max_attempts=10,  # Many attempts allowed
        )

        claim_job(service_client, ["email_fetch"], "test-worker")

        # Fail without retry
        fail_job(service_client, job_id, "Permanent error", retry=False)

        # Verify job is dead despite having attempts left
        job = get_job_status(service_client, job_id)
        assert job["status"] == "dead"


@pytest.mark.integration
@pytest.mark.development
class TestWorkerConcurrency:
    """Tests for concurrent worker behavior."""

    def test_multiple_workers_get_different_jobs(self, service_client, test_user_id):
        """Test that multiple workers claim different jobs."""
        # Enqueue multiple jobs
        job_ids = []
        for i in range(3):
            job_id = enqueue_job(
                service_client,
                user_id=test_user_id,
                job_type="email_fetch",
                payload={"index": i},
            )
            job_ids.append(job_id)

        # Multiple workers claim jobs
        claimed_ids = set()
        for i in range(3):
            claimed = claim_job(service_client, ["email_fetch"], f"worker-{i}")
            if claimed:
                claimed_ids.add(claimed["id"])

        # All jobs should be claimed by different workers
        assert len(claimed_ids) == 3
        assert claimed_ids == set(job_ids)

    def test_worker_cannot_claim_locked_job(self, service_client, test_user_id):
        """Test that a worker cannot claim a job locked by another worker."""
        # Enqueue single job
        job_id = enqueue_job(
            service_client,
            user_id=test_user_id,
            job_type="email_fetch",
            payload={},
        )

        # Worker 1 claims it
        claimed_1 = claim_job(service_client, ["email_fetch"], "worker-1")
        assert claimed_1["id"] == job_id

        # Worker 2 tries to claim - should get nothing
        claimed_2 = claim_job(service_client, ["email_fetch"], "worker-2")
        assert claimed_2 is None

        # Worker 1 completes
        complete_job(service_client, job_id)

        # Now worker 3 should not be able to claim (job is completed)
        claimed_3 = claim_job(service_client, ["email_fetch"], "worker-3")
        assert claimed_3 is None
