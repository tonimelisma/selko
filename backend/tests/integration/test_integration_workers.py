"""Integration tests for status-based worker processing.

Tests the worker job handlers with real Supabase database but mocked
external APIs (Gmail, Google Calendar, Gemini).
"""

import asyncio
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


@pytest.fixture
def test_user_id(isolated_user):
    """Use a throwaway user so worker claim batches cannot cross tests."""
    return isolated_user["id"]


@pytest.fixture
def authenticated_client(service_client):
    """Worker tests use service-role writes for their isolated user."""
    return service_client


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

    # Remove calendar work items so claims cannot cross test boundaries.
    try:
        service_client.table("calendar_work_items").delete().eq(
            "user_id", test_user_id
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

    async def test_claim_pending_email_directly(
        self, service_client, authenticated_client, test_user_id, pg_pool
    ):
        """Test that worker can claim a pending email directly from the emails table."""
        # Create a pending email
        email_data = {
            "user_id": test_user_id,
            "provider_message_id": f"claim-test-{uuid4().hex[:8]}",
            "subject": "Test Email for Claiming",
            "from_email": "test@example.com",
            "date_sent": "1900-01-01T00:00:00Z",
            "snippet": "Test content",
            "provider_labels": ["INBOX"],
            "processing_status": "pending",
        }

        result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = result.data[0]["id"]

        # Claim the email
        claimed = await claim_pending_email(pg_pool, "test-worker-1")

        assert claimed is not None
        assert str(claimed["id"]) == email_id
        assert claimed["processing_status"] == "processing"
        assert claimed["locked_by"] == "test-worker-1"
        assert claimed["attempts"] == 1

    async def test_complete_email_processing_updates_status(
        self, service_client, authenticated_client, test_user_id, pg_pool
    ):
        """Test that completing email processing updates status correctly."""
        # Create and claim an email
        email_data = {
            "user_id": test_user_id,
            "provider_message_id": f"complete-test-{uuid4().hex[:8]}",
            "subject": "Test Email",
            "from_email": "test@example.com",
            "date_sent": "2000-01-01T00:00:00Z",
            "processing_status": "pending",
            "provider_labels": ["INBOX"],
        }

        result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = result.data[0]["id"]

        await claim_pending_email(pg_pool, "test-worker")

        # Complete processing
        await complete_email_processing(pg_pool, email_id)

        # Verify status
        email = authenticated_client.table("emails").select("*").eq(
            "id", email_id
        ).single().execute()

        assert email.data["processing_status"] == "processed"
        assert email.data["processed_at"] is not None
        assert email.data["locked_by"] is None

    async def test_fail_email_processing_with_retry(
        self, service_client, authenticated_client, test_user_id, pg_pool
    ):
        """Test that failing email processing allows retry."""
        # Create email with max_attempts=3
        email_data = {
            "user_id": test_user_id,
            "provider_message_id": f"fail-test-{uuid4().hex[:8]}",
            "subject": "Test Email",
            "from_email": "test@example.com",
            "date_sent": "2000-01-01T00:00:00Z",
            "processing_status": "pending",
            "provider_labels": ["INBOX"],
            "max_attempts": 3,
        }

        result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = result.data[0]["id"]

        # Claim and fail
        claimed = await claim_pending_email(pg_pool, "worker-1")
        await fail_email_processing(
            pg_pool, email_id, "worker-1", claimed["lock_generation"],
            "Test error", 60, 1800,
        )

        # Should be back to pending for retry
        email = authenticated_client.table("emails").select("*").eq(
            "id", email_id
        ).single().execute()

        assert email.data["processing_status"] == "pending"
        assert email.data["processing_error"] == "Test error"
        assert email.data["locked_by"] is None

    async def test_concurrent_workers_no_duplicate_email_processing(
        self, service_client, authenticated_client, test_user_id, pg_pool
    ):
        """Test that SKIP LOCKED prevents concurrent workers from claiming same email."""
        # Clean up any existing pending emails first
        service_client.table("emails").update({
            "processing_status": "processed"
        }).eq("user_id", test_user_id).eq("processing_status", "pending").execute()

        # Create a single email
        email_data = {
            "user_id": test_user_id,
            "provider_message_id": f"concurrent-test-{uuid4().hex[:8]}",
            "subject": "Test Email",
            "from_email": "test@example.com",
            # Keep this row ahead of unrelated global queue work.
            "date_sent": "1900-01-01T00:00:00Z",
            "processing_status": "pending",
            "provider_labels": ["INBOX"],
        }

        result = authenticated_client.table("emails").insert(email_data).execute()
        email_id = result.data[0]["id"]

        # The claim RPC is global. Consume unrelated rows until this test's
        # row is the one under test, then assert the ownership property.
        claimed_1 = None
        for _ in range(20):
            candidate = await claim_pending_email(pg_pool, "worker-1")
            if candidate is None:
                break
            if str(candidate["id"]) == email_id:
                claimed_1 = candidate
                break
            await complete_email_processing(pg_pool, str(candidate["id"]))
        assert claimed_1 is not None

        # Worker 2 must not claim the same email, even if another global row
        # is available in the bounded queue.
        claimed_2 = await claim_pending_email(pg_pool, "worker-2")
        assert claimed_2 is None or str(claimed_2["id"]) != email_id

    async def test_email_lock_expiry_recovery(
        self, service_client, authenticated_client, test_user_id, pg_pool
    ):
        """Test that expired email locks can be recovered."""
        # Create and claim an email with short lock
        provider_message_id = f"expiry-test-{uuid4().hex[:8]}"
        email_data = {
            "user_id": test_user_id,
            "provider_message_id": provider_message_id,
            "subject": "Test Email",
            "from_email": "test@example.com",
            # The claim RPC is intentionally global and oldest-first; make
            # this test's row win even when another isolated test left work.
            "date_sent": "2000-01-01T00:00:00Z",
            "processing_status": "pending",
            "provider_labels": ["INBOX"],
        }

        authenticated_client.table("emails").insert(email_data).execute()

        await claim_pending_email(pg_pool, "worker-1", lock_duration_seconds=1)

        # Set lock_until to past directly instead of waiting
        past_time = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        service_client.table("emails").update({
            "locked_until": past_time
        }).eq("provider_message_id", provider_message_id).execute()

        # Unlock expired locks
        count = await unlock_expired_email_locks(pg_pool)
        assert count >= 1

        # Should be claimable again
        claimed = await claim_pending_email(pg_pool, "worker-2")
        assert claimed is not None


@pytest.mark.integration
@pytest.mark.development
class TestEventStatusBasedClaiming:
    """Tests for event status-based claiming (replacing calendar_sync jobs)."""

    @pytest.fixture(autouse=True)
    def _active_google_calendar_integration(self, service_client, test_user_id):
        """claim_approved_event requires an active google_calendar integration
        for the event's user (oauth-reconnect-catch-up.md structured failure
        classification: workers must not burn attempts on users who are
        known to be disconnected).
        """
        service_client.table("integrations").upsert(
            {
                "user_id": test_user_id,
                "provider": "google_calendar",
                "status": "active",
                "access_token": "test-access-token",
            },
            on_conflict="user_id,provider",
        ).execute()
        yield
        service_client.table("integrations").delete().eq(
            "user_id", test_user_id
        ).eq("provider", "google_calendar").execute()

    async def test_claim_approved_event_directly(
        self, service_client, authenticated_client, test_user_id, pg_pool
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
        authenticated_client.rpc("enqueue_calendar_work", {
            "p_event_id": event_id,
            "p_user_id": test_user_id,
            "p_action": "upsert",
            "p_desired_event": {"title": event_data["title"]},
        }).execute()

        # Claim the event
        claimed = await claim_approved_event_for_sync(pg_pool, "test-worker-1")

        assert claimed is not None
        assert str(claimed["id"]) == event_id
        assert claimed["status"] == "syncing"
        assert claimed["calendar_work_item_action"] == "upsert"
        assert claimed["calendar_work_item_attempts"] == 1

    async def test_complete_event_sync_updates_status(
        self, service_client, authenticated_client, test_user_id, pg_pool
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
        authenticated_client.rpc("enqueue_calendar_work", {
            "p_event_id": event_id,
            "p_user_id": test_user_id,
            "p_action": "upsert",
            "p_desired_event": {"title": event_data["title"]},
        }).execute()

        claimed = await claim_approved_event_for_sync(pg_pool, "test-worker")

        # Complete sync
        await complete_event_sync(
            pg_pool,
            event_id,
            "google-event-123",
            "test-worker",
            int(claimed["calendar_work_item_generation"]),
        )

        # Verify status
        event = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()

        assert event.data["status"] == "synced"
        assert event.data["google_calendar_event_id"] == "google-event-123"
        assert event.data["synced_at"] is not None

    async def test_fail_event_sync_with_retry(
        self, service_client, authenticated_client, test_user_id, pg_pool
    ):
        """Test that failing event sync allows retry."""
        # The work item owns the retry budget.
        event_data = {
            "user_id": test_user_id,
            "title": "Test Event",
            "start_datetime": "2026-05-01T14:00:00Z",
            "status": "approved",
        }

        result = authenticated_client.table("events").insert(event_data).execute()
        event_id = result.data[0]["id"]
        authenticated_client.rpc("enqueue_calendar_work", {
            "p_event_id": event_id,
            "p_user_id": test_user_id,
            "p_action": "upsert",
            "p_desired_event": {"title": event_data["title"]},
        }).execute()

        # Claim and fail
        claimed = await claim_approved_event_for_sync(pg_pool, "worker-1")
        await fail_event_sync(
            pg_pool,
            event_id,
            "Test sync error",
            "worker-1",
            int(claimed["calendar_work_item_generation"]),
        )

        # Should be back to approved for retry
        event = authenticated_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()

        assert event.data["status"] == "approved"
        work_item = authenticated_client.table("calendar_work_items").select(
            "status,failure_code,failure_detail,locked_by"
        ).eq("event_id", event_id).single().execute().data
        assert work_item["status"] == "pending"
        assert work_item["failure_code"] == "calendar_sync_failed"
        assert work_item["failure_detail"] == "Test sync error"
        assert work_item["locked_by"] is None

    async def test_concurrent_workers_no_duplicate_event_sync(
        self, service_client, authenticated_client, test_user_id, pg_pool
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
        event_id = authenticated_client.table("events").select("id").eq(
            "user_id", test_user_id
        ).eq("title", "Test Event").single().execute().data["id"]
        authenticated_client.rpc("enqueue_calendar_work", {
            "p_event_id": event_id,
            "p_user_id": test_user_id,
            "p_action": "upsert",
            "p_desired_event": {"title": event_data["title"]},
        }).execute()

        # Worker 1 claims it
        claimed_1 = await claim_approved_event_for_sync(pg_pool, "worker-1")
        assert claimed_1 is not None

        # Worker 2 tries to claim - should get None (only one event exists)
        claimed_2 = await claim_approved_event_for_sync(pg_pool, "worker-2")
        assert claimed_2 is None

    async def test_claim_excludes_users_without_active_calendar_integration(
        self, service_client, authenticated_client, test_user_id, pg_pool
    ):
        """An expired google_calendar integration must not be claimed for sync.

        Otherwise workers keep burning sync_attempts toward dead-letter on a
        user who is already known to need reauthorization.
        """
        service_client.table("integrations").update({"status": "expired"}).eq(
            "user_id", test_user_id
        ).eq("provider", "google_calendar").execute()

        event_data = {
            "user_id": test_user_id,
            "title": "Blocked on expired calendar auth",
            "start_datetime": "2026-05-01T14:00:00Z",
            "status": "approved",
        }
        authenticated_client.table("events").insert(event_data).execute()
        event_id = authenticated_client.table("events").select("id").eq(
            "user_id", test_user_id
        ).eq("title", event_data["title"]).single().execute().data["id"]
        authenticated_client.rpc("enqueue_calendar_work", {
            "p_event_id": event_id,
            "p_user_id": test_user_id,
            "p_action": "upsert",
            "p_desired_event": {"title": event_data["title"]},
        }).execute()

        claimed = await claim_approved_event_for_sync(pg_pool, "worker-1")
        assert claimed is None


@pytest.mark.integration
@pytest.mark.development
class TestScheduledTasks:
    """Tests for scheduled tasks (photo_fetch only)."""

    def test_enqueue_and_claim_scheduled_task(
        self, service_client, test_user_id, pg_pool
    ):
        """Test basic scheduled task enqueue and claim operations."""
        # Enqueue a task
        task_id = enqueue_scheduled_task(
            service_client,
            user_id=test_user_id,
            task_type="photo_fetch",
            payload={"max_emails": 50},
        )

        assert task_id is not None

        # Claim the task
        claimed = claim_scheduled_task(
            service_client,
            task_types=["photo_fetch"],
            worker_id="test-worker-1",
        )

        assert claimed is not None
        assert claimed["id"] == task_id
        assert claimed["status"] == "processing"
        assert claimed["locked_by"] == "test-worker-1"

    async def test_complete_scheduled_task(
        self, service_client, test_user_id, pg_pool
    ):
        """Test marking a scheduled task as completed."""
        # Enqueue and claim
        task_id = enqueue_scheduled_task(
            service_client,
            user_id=test_user_id,
            task_type="photo_fetch",
            payload={},
        )

        claim_scheduled_task(service_client, ["photo_fetch"], "test-worker")

        # Complete
        complete_scheduled_task(service_client, task_id)

        # Verify
        task = service_client.table("scheduled_tasks").select("*").eq(
            "id", task_id
        ).single().execute()

        assert task.data["status"] == "completed"
        assert task.data["completed_at"] is not None
        assert task.data["locked_by"] is None

    async def test_fail_scheduled_task(
        self, service_client, test_user_id, pg_pool
    ):
        """Test marking a scheduled task as failed."""
        # Enqueue and claim
        task_id = enqueue_scheduled_task(
            service_client,
            user_id=test_user_id,
            task_type="photo_fetch",
            payload={},
        )

        claim_scheduled_task(service_client, ["photo_fetch"], "test-worker")

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
        self, service_client, authenticated_client, test_user_id, config, mock_llm_gateway
    ):
        """Test that email_process worker extracts events from email."""
        from selko.workers.email_process import process_email

        # Create a test email
        email_data = {
            "user_id": test_user_id,
            "provider_message_id": f"worker-test-{uuid4().hex[:8]}",
            "subject": "Birthday Party Invitation",
            "from_email": "friend@example.com",
            "from_name": "Best Friend",
            "date_sent": "2000-01-01T00:00:00Z",
            "snippet": "You're invited to Jake's birthday party on May 20th at 2pm!",
            "provider_labels": ["INBOX"],
            "processing_status": "pending",
        }

        result = authenticated_client.table("emails").insert(email_data).execute()
        email = result.data[0]

        # Process with mocked LLM Gateway. The worker builds its gateway via
        # create_llm_gateway(); patching the old LLMGateway symbol silently
        # stopped matching when that factory was introduced.
        with patch(
            "selko.workers.email_process.create_llm_gateway",
            return_value=mock_llm_gateway,
        ):
            await process_email(service_client, config, email)

        # Note: The worker doesn't update status directly - that's done by pool.py
        # We just verify no exception was raised


@pytest.mark.integration
@pytest.mark.development
class TestWorkerConcurrency:
    """Tests for concurrent worker behavior."""

    @pytest.fixture(autouse=True)
    def _active_google_calendar_integration(self, service_client, test_user_id):
        """claim_approved_event requires an active google_calendar integration
        for the event's user (oauth-reconnect-catch-up.md structured failure
        classification). TestEventStatusBasedClaiming got this fixture in #236;
        the concurrency class missed it, so its event-claiming test only passed
        when a seeded calendar integration happened to be active."""
        service_client.table("integrations").upsert(
            {
                "user_id": test_user_id,
                "provider": "google_calendar",
                "status": "active",
                "access_token": "test-access-token",
            },
            on_conflict="user_id,provider",
        ).execute()
        yield
        service_client.table("integrations").delete().eq(
            "user_id", test_user_id
        ).eq("provider", "google_calendar").execute()

    async def test_multiple_workers_get_different_emails(
        self, service_client, authenticated_client, test_user_id, pg_pool
    ):
        """Test that multiple workers claim different emails."""
        # Create multiple pending emails
        email_ids = []
        for i in range(3):
            email_data = {
                "user_id": test_user_id,
                "provider_message_id": f"multi-test-{uuid4().hex[:8]}",
                "subject": f"Test Email {i}",
                "from_email": "test@example.com",
                "date_sent": "2000-01-01T00:00:00Z",
                "processing_status": "pending",
                "provider_labels": ["INBOX"],
            }
            result = authenticated_client.table("emails").insert(email_data).execute()
            email_ids.append(result.data[0]["id"])

        # Multiple workers claim emails
        claimed_ids = set()
        for i in range(3):
            claimed = await claim_pending_email(pg_pool, f"worker-{i}")
            if claimed:
                claimed_ids.add(str(claimed["id"]))

        # All emails should be claimed by different workers
        assert len(claimed_ids) == 3
        assert claimed_ids == {str(i) for i in email_ids}

    async def test_multiple_workers_get_different_events(
        self, service_client, authenticated_client, test_user_id, pg_pool
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
            claimed = await claim_approved_event_for_sync(pg_pool, f"worker-{i}")
            if claimed:
                claimed_ids.add(str(claimed["id"]))

        # All events should be claimed by different workers
        assert len(claimed_ids) == 3
        assert claimed_ids == {str(i) for i in event_ids}
