"""Integration tests for status-based worker processing.

Tests the worker job handlers with real Supabase database but mocked
external APIs (Gmail, Google Calendar, Gemini).
"""

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from supabase import Client

from selko.config import Config
from selko.services.auth import get_service_client
from selko.services.emails import (
    claim_pending_email,
    complete_email_processing,
    fail_email_processing,
    unlock_expired_email_locks,
)
from selko.services.events import (
    claim_approved_event_for_sync,
    complete_event_sync,
    fail_event_sync,
    unlock_expired_event_locks,
)
from selko.services.scheduled_tasks import (
    claim_scheduled_task,
    complete_scheduled_task,
    enqueue_scheduled_task,
    fail_scheduled_task,
    unlock_expired_scheduled_tasks,
)

logger = logging.getLogger(__name__)


@pytest.fixture
def service_client(config: Config) -> Client:
    """Get a service role client for testing worker operations."""
    return get_service_client(config)


@pytest.fixture(autouse=True)
def cleanup_test_data(service_client: Client, test_user_id: str):
    """Clean up all test data before and after each test."""
    # Clean up scheduled tasks
    try:
        service_client.table("scheduled_tasks").delete().eq("user_id", test_user_id).execute()
    except Exception as e:
        logger.warning(f"Failed to cleanup scheduled tasks: {e}")

    # Reset any pending emails to processed to avoid test pollution
    try:
        service_client.table("emails").update({
            "processing_status": "processed",
            "locked_by": None,
            "locked_until": None,
        }).eq("user_id", test_user_id).in_(
            "processing_status", ["pending", "processing"]
        ).execute()
    except Exception as e:
        logger.warning(f"Failed to reset pending emails: {e}")

    # Reset any approved/syncing events to synced to avoid test pollution
    try:
        service_client.table("events").update({
            "status": "synced",
            "locked_by": None,
            "locked_until": None,
        }).eq("user_id", test_user_id).in_(
            "status", ["approved", "syncing"]
        ).execute()
    except Exception as e:
        logger.warning(f"Failed to reset approved events: {e}")

    yield

    # Clean up after test
    try:
        service_client.table("scheduled_tasks").delete().eq("user_id", test_user_id).execute()
    except Exception as e:
        logger.warning(f"Failed to cleanup scheduled tasks after test: {e}")


@pytest.mark.integration
@pytest.mark.development
class TestEmailStatusBasedClaiming:
    """Tests for email status-based claiming (replacing email_process jobs)."""

    def test_claim_pending_email_directly(
        self, service_client, authenticated_client, test_user_id
    ):
        """Test that worker can claim a pending email directly from the emails table."""
        # Create a pending email
        email_data = {
            "user_id": test_user_id,
            "gmail_id": f"claim-test-{uuid4().hex[:8]}",
            "subject": "Test Email for Claiming",
            "from_email": "test@example.com",
            "date_sent": "2026-05-15T12:00:00Z",
            "snippet": "Test content",
            "gmail_label_ids": ["INBOX"],
            "processing_status": "pending",
        }

        result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = result.data[0]["id"]

        # Claim the email
        claimed = claim_pending_email(service_client, "test-worker-1")

        assert claimed is not None
        assert claimed["id"] == email_id
        assert claimed["processing_status"] == "processing"
        assert claimed["locked_by"] == "test-worker-1"
        assert claimed["attempts"] == 1

    def test_complete_email_processing_updates_status(
        self, service_client, authenticated_client, test_user_id
    ):
        """Test that completing email processing updates status correctly."""
        # Create and claim an email
        email_data = {
            "user_id": test_user_id,
            "gmail_id": f"complete-test-{uuid4().hex[:8]}",
            "subject": "Test Email",
            "from_email": "test@example.com",
            "processing_status": "pending",
            "gmail_label_ids": ["INBOX"],
        }

        result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = result.data[0]["id"]

        claim_pending_email(service_client, "test-worker")

        # Complete processing
        complete_email_processing(service_client, email_id)

        # Verify status
        email = authenticated_client.table("emails").select("*").eq(
            "id", email_id
        ).single().execute()

        assert email.data["processing_status"] == "processed"
        assert email.data["processed_at"] is not None
        assert email.data["locked_by"] is None

    def test_fail_email_processing_with_retry(
        self, service_client, authenticated_client, test_user_id
    ):
        """Test that failing email processing allows retry."""
        # Create email with max_attempts=3
        email_data = {
            "user_id": test_user_id,
            "gmail_id": f"fail-test-{uuid4().hex[:8]}",
            "subject": "Test Email",
            "from_email": "test@example.com",
            "processing_status": "pending",
            "gmail_label_ids": ["INBOX"],
            "max_attempts": 3,
        }

        result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = result.data[0]["id"]

        # Claim and fail
        claim_pending_email(service_client, "worker-1")
        fail_email_processing(service_client, email_id, "Test error")

        # Should be back to pending for retry
        email = authenticated_client.table("emails").select("*").eq(
            "id", email_id
        ).single().execute()

        assert email.data["processing_status"] == "pending"
        assert email.data["processing_error"] == "Test error"
        assert email.data["locked_by"] is None

    def test_concurrent_workers_no_duplicate_email_processing(
        self, service_client, authenticated_client, test_user_id
    ):
        """Test that SKIP LOCKED prevents concurrent workers from claiming same email."""
        # Clean up any existing pending emails first
        service_client.table("emails").update({
            "processing_status": "processed"
        }).eq("user_id", test_user_id).eq("processing_status", "pending").execute()

        # Create a single email
        email_data = {
            "user_id": test_user_id,
            "gmail_id": f"concurrent-test-{uuid4().hex[:8]}",
            "subject": "Test Email",
            "from_email": "test@example.com",
            "processing_status": "pending",
            "gmail_label_ids": ["INBOX"],
        }

        authenticated_client.table("emails").insert(email_data).execute()

        # Worker 1 claims it
        claimed_1 = claim_pending_email(service_client, "worker-1")
        assert claimed_1 is not None

        # Worker 2 tries to claim - should get None (only one email exists)
        claimed_2 = claim_pending_email(service_client, "worker-2")
        assert claimed_2 is None

    def test_email_lock_expiry_recovery(
        self, service_client, authenticated_client, test_user_id
    ):
        """Test that expired email locks can be recovered."""
        # Create and claim an email with short lock
        gmail_id = f"expiry-test-{uuid4().hex[:8]}"
        email_data = {
            "user_id": test_user_id,
            "gmail_id": gmail_id,
            "subject": "Test Email",
            "from_email": "test@example.com",
            "processing_status": "pending",
            "gmail_label_ids": ["INBOX"],
        }

        authenticated_client.table("emails").insert(email_data).execute()

        claim_pending_email(service_client, "worker-1", lock_duration_seconds=1)

        # Set lock_until to past directly instead of waiting
        past_time = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        service_client.table("emails").update({
            "locked_until": past_time
        }).eq("gmail_id", gmail_id).execute()

        # Unlock expired locks
        count = unlock_expired_email_locks(service_client)
        assert count >= 1

        # Should be claimable again
        claimed = claim_pending_email(service_client, "worker-2")
        assert claimed is not None


@pytest.mark.integration
@pytest.mark.development
class TestEventStatusBasedClaiming:
    """Tests for event status-based claiming (replacing calendar_sync jobs)."""

    def test_claim_approved_event_directly(
        self, service_client, authenticated_client, test_user_id
    ):
        """Test that worker can claim an approved event directly."""
        # Create an approved event
        event_data = {
            "user_id": test_user_id,
            "title": "Test Event for Claiming",
            "start_datetime": "2026-05-01T14:00:00Z",
            "status": "approved",
        }

        result = authenticated_client.table("events").insert(event_data).execute()
        event_id = result.data[0]["id"]

        # Claim the event
        claimed = claim_approved_event_for_sync(service_client, "test-worker-1")

        assert claimed is not None
        assert claimed["id"] == event_id
        assert claimed["status"] == "syncing"
        assert claimed["locked_by"] == "test-worker-1"
        assert claimed["sync_attempts"] == 1

    def test_complete_event_sync_updates_status(
        self, service_client, authenticated_client, test_user_id
    ):
        """Test that completing event sync updates status correctly."""
        # Create and claim an event
        event_data = {
            "user_id": test_user_id,
            "title": "Test Event",
            "start_datetime": "2026-05-01T14:00:00Z",
            "status": "approved",
        }

        result = authenticated_client.table("events").insert(event_data).execute()
        event_id = result.data[0]["id"]

        claim_approved_event_for_sync(service_client, "test-worker")

        # Complete sync
        complete_event_sync(service_client, event_id, "google-event-123")

        # Verify status
        event = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()

        assert event.data["status"] == "synced"
        assert event.data["google_calendar_event_id"] == "google-event-123"
        assert event.data["synced_at"] is not None
        assert event.data["locked_by"] is None

    def test_fail_event_sync_with_retry(
        self, service_client, authenticated_client, test_user_id
    ):
        """Test that failing event sync allows retry."""
        # Create event with max_sync_attempts=3
        event_data = {
            "user_id": test_user_id,
            "title": "Test Event",
            "start_datetime": "2026-05-01T14:00:00Z",
            "status": "approved",
            "max_sync_attempts": 3,
        }

        result = authenticated_client.table("events").insert(event_data).execute()
        event_id = result.data[0]["id"]

        # Claim and fail
        claim_approved_event_for_sync(service_client, "worker-1")
        fail_event_sync(service_client, event_id, "Test sync error")

        # Should be back to approved for retry
        event = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()

        assert event.data["status"] == "approved"
        assert event.data["sync_error"] == "Test sync error"
        assert event.data["locked_by"] is None

    def test_concurrent_workers_no_duplicate_event_sync(
        self, service_client, authenticated_client, test_user_id
    ):
        """Test that SKIP LOCKED prevents concurrent workers from claiming same event."""
        # Clean up any existing approved events first
        service_client.table("events").update({
            "status": "synced"
        }).eq("user_id", test_user_id).eq("status", "approved").execute()

        # Create a single event
        event_data = {
            "user_id": test_user_id,
            "title": "Test Event",
            "start_datetime": "2026-05-01T14:00:00Z",
            "status": "approved",
        }

        authenticated_client.table("events").insert(event_data).execute()

        # Worker 1 claims it
        claimed_1 = claim_approved_event_for_sync(service_client, "worker-1")
        assert claimed_1 is not None

        # Worker 2 tries to claim - should get None (only one event exists)
        claimed_2 = claim_approved_event_for_sync(service_client, "worker-2")
        assert claimed_2 is None


@pytest.mark.integration
@pytest.mark.development
class TestScheduledTasks:
    """Tests for scheduled tasks (email_fetch only)."""

    def test_enqueue_and_claim_scheduled_task(
        self, service_client, test_user_id
    ):
        """Test basic scheduled task enqueue and claim operations."""
        # Enqueue a task
        task_id = enqueue_scheduled_task(
            service_client,
            user_id=test_user_id,
            task_type="email_fetch",
            payload={"max_emails": 50},
        )

        assert task_id is not None

        # Claim the task
        claimed = claim_scheduled_task(
            service_client,
            task_types=["email_fetch"],
            worker_id="test-worker-1",
        )

        assert claimed is not None
        assert claimed["id"] == task_id
        assert claimed["status"] == "processing"
        assert claimed["locked_by"] == "test-worker-1"

    def test_complete_scheduled_task(
        self, service_client, test_user_id
    ):
        """Test marking a scheduled task as completed."""
        # Enqueue and claim
        task_id = enqueue_scheduled_task(
            service_client,
            user_id=test_user_id,
            task_type="email_fetch",
            payload={},
        )

        claim_scheduled_task(service_client, ["email_fetch"], "test-worker")

        # Complete
        complete_scheduled_task(service_client, task_id)

        # Verify
        task = service_client.table("scheduled_tasks").select("*").eq(
            "id", task_id
        ).single().execute()

        assert task.data["status"] == "completed"
        assert task.data["completed_at"] is not None
        assert task.data["locked_by"] is None

    def test_fail_scheduled_task(
        self, service_client, test_user_id
    ):
        """Test marking a scheduled task as failed."""
        # Enqueue and claim
        task_id = enqueue_scheduled_task(
            service_client,
            user_id=test_user_id,
            task_type="email_fetch",
            payload={},
        )

        claim_scheduled_task(service_client, ["email_fetch"], "test-worker")

        # Fail
        fail_scheduled_task(service_client, task_id, "Test error")

        # Verify - scheduled tasks don't retry
        task = service_client.table("scheduled_tasks").select("*").eq(
            "id", task_id
        ).single().execute()

        assert task.data["status"] == "failed"
        assert task.data["last_error"] == "Test error"


@pytest.mark.integration
@pytest.mark.development
class TestCalendarSyncWorker:
    """Tests for calendar_sync worker with mocked Google API."""

    @pytest.mark.asyncio
    async def test_processes_approved_event(
        self, service_client, authenticated_client, test_user_id, config
    ):
        """Test that calendar_sync worker processes an approved event."""
        from selko.workers.calendar_sync import sync_event

        # Create an approved event
        event_data = {
            "user_id": test_user_id,
            "title": "Worker Test Event",
            "start_datetime": "2026-05-01T14:00:00Z",
            "end_datetime": "2026-05-01T15:00:00Z",
            "status": "approved",
        }

        result = authenticated_client.table("events").insert(event_data).execute()
        event = result.data[0]

        # Mock Google Calendar API
        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()

            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.insert.return_value.execute.return_value = {
                "id": "google-worker-test-123"
            }

            # Process the event
            google_event_id = await sync_event(service_client, config, event)

        assert google_event_id == "google-worker-test-123"


@pytest.mark.integration
@pytest.mark.development
class TestEmailProcessWorker:
    """Tests for email_process worker with mocked Gemini."""

    @pytest.mark.asyncio
    async def test_processes_email_for_events(
        self, service_client, authenticated_client, test_user_id, config, mock_gemini_client
    ):
        """Test that email_process worker extracts events from email."""
        from selko.workers.email_process import process_email

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
        email = result.data[0]

        # Process with mocked Gemini
        with patch("selko.workers.email_process.get_gemini_client") as mock_get_gemini:
            mock_get_gemini.return_value = mock_gemini_client

            await process_email(service_client, config, email)

        # Note: The worker doesn't update status directly - that's done by pool.py
        # We just verify no exception was raised


@pytest.mark.integration
@pytest.mark.development
class TestWorkerConcurrency:
    """Tests for concurrent worker behavior."""

    def test_multiple_workers_get_different_emails(
        self, service_client, authenticated_client, test_user_id
    ):
        """Test that multiple workers claim different emails."""
        # Create multiple pending emails
        email_ids = []
        for i in range(3):
            email_data = {
                "user_id": test_user_id,
                "gmail_id": f"multi-test-{uuid4().hex[:8]}",
                "subject": f"Test Email {i}",
                "from_email": "test@example.com",
                "processing_status": "pending",
                "gmail_label_ids": ["INBOX"],
            }
            result = authenticated_client.table("emails").insert(email_data).execute()
            email_ids.append(result.data[0]["id"])

        # Multiple workers claim emails
        claimed_ids = set()
        for i in range(3):
            claimed = claim_pending_email(service_client, f"worker-{i}")
            if claimed:
                claimed_ids.add(claimed["id"])

        # All emails should be claimed by different workers
        assert len(claimed_ids) == 3
        assert claimed_ids == set(email_ids)

    def test_multiple_workers_get_different_events(
        self, service_client, authenticated_client, test_user_id
    ):
        """Test that multiple workers claim different events."""
        # Create multiple approved events
        event_ids = []
        for i in range(3):
            event_data = {
                "user_id": test_user_id,
                "title": f"Test Event {i}",
                "start_datetime": f"2026-05-0{i+1}T14:00:00Z",
                "status": "approved",
            }
            result = authenticated_client.table("events").insert(event_data).execute()
            event_ids.append(result.data[0]["id"])

        # Multiple workers claim events
        claimed_ids = set()
        for i in range(3):
            claimed = claim_approved_event_for_sync(service_client, f"worker-{i}")
            if claimed:
                claimed_ids.add(claimed["id"])

        # All events should be claimed by different workers
        assert len(claimed_ids) == 3
        assert claimed_ids == set(event_ids)
