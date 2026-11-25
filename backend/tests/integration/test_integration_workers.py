"""Integration tests for status-based worker processing.

Email and calendar claiming run on a real SQLite database (`db`/`factory`);
external APIs (Gmail, Google Calendar, the LLM) stay mocked.
"""

import asyncio
import logging
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from selko.services.emails import (
    claim_pending_email,
    complete_email_processing,
    fail_email_processing,
    unlock_expired_email_locks,
)

logger = logging.getLogger(__name__)


def _pending_email(factory, user_id: str, *, date_sent: str = "2000-01-01T00:00:00.000000Z", **extra) -> str:
    return factory.email(
        user_id,
        provider_message_id=f"claim-test-{uuid4().hex[:8]}",
        subject=extra.pop("subject", "Test Email"),
        from_email="test@example.com",
        date_sent=date_sent,
        provider_labels=["INBOX"],
        **extra,
    )


@pytest.mark.integration
class TestEmailStatusBasedClaiming:
    """Email status-based claiming on the real database."""

    async def test_claim_pending_email_directly(self, db, factory):
        """A worker claims a pending email directly from the emails table."""
        email_id = _pending_email(factory, factory.user(), date_sent="1900-01-01T00:00:00.000000Z")

        claimed = await claim_pending_email(db, "test-worker-1")

        assert claimed is not None
        assert claimed["id"] == email_id
        assert claimed["processing_status"] == "processing"
        assert claimed["locked_by"] == "test-worker-1"
        assert claimed["attempts"] == 1

    async def test_complete_email_processing_updates_status(self, db, factory):
        email_id = _pending_email(factory, factory.user())
        await claim_pending_email(db, "test-worker")

        await complete_email_processing(db, email_id)

        email = factory.row("emails", email_id)
        assert email["processing_status"] == "processed"
        assert email["processed_at"] is not None
        assert email["locked_by"] is None

    async def test_fail_email_processing_with_retry(self, db, factory):
        email_id = _pending_email(factory, factory.user(), max_attempts=3)

        claimed = await claim_pending_email(db, "worker-1")
        await fail_email_processing(
            db, email_id, "worker-1", claimed["lock_generation"], "Test error", 60, 1800,
        )

        email = factory.row("emails", email_id)
        assert email["processing_status"] == "pending"
        assert email["processing_error"] == "Test error"
        assert email["locked_by"] is None

    async def test_concurrent_workers_no_duplicate_email_processing(self, db, factory):
        """Concurrent claimers over the single writer never share an email."""
        email_id = _pending_email(factory, factory.user())

        results = await asyncio.gather(*(claim_pending_email(db, f"worker-{i}") for i in range(10)))

        claimed = [r for r in results if r is not None]
        assert [r["id"] for r in claimed] == [email_id]
        assert factory.row("emails", email_id)["lock_generation"] == claimed[0]["lock_generation"]

    async def test_email_lock_expiry_recovery(self, db, factory):
        """An expired lease is released and the email is claimable again."""
        email_id = _pending_email(factory, factory.user())
        await claim_pending_email(db, "worker-1", lock_duration_seconds=1)
        with db.write() as tx:
            tx.execute("UPDATE emails SET locked_until = ? WHERE id = ?", (tx.ts(-10), email_id))

        count = await unlock_expired_email_locks(db)
        assert count == 1

        claimed = await claim_pending_email(db, "worker-2")
        assert claimed is not None and claimed["id"] == email_id
        assert claimed["attempts"] == 2


@pytest.mark.integration
class TestEventStatusBasedClaiming:
    """Calendar work claiming on a real SQLite database (`selko.db.calendar_work`)."""

    @pytest.fixture
    def calendar_user(self, factory):
        """The claim requires an active calendar integration for the event's user
        (oauth-reconnect-catch-up.md structured failure classification: workers
        must not burn attempts on users who are known to be disconnected).
        """
        user_id = factory.user()
        factory.integration(user_id, provider="google_calendar", access_token="test-access-token")
        return user_id

    @staticmethod
    def _queued_event(db, factory, user_id, title="Test Event", review_status="active"):
        from selko.db import calendar_work

        event_id = factory.event(
            user_id, review_status=review_status, title=title,
            start_datetime="2026-05-01T14:00:00.000000Z",
        )
        calendar_work.enqueue_calendar_work(db, user_id, event_id, "upsert", {"title": title})
        return event_id

    async def test_claim_approved_event_directly(self, db, factory, calendar_user):
        """Test that worker can claim an approved event directly."""
        from selko.db import calendar_work

        event_id = self._queued_event(db, factory, calendar_user, "Test Event for Claiming")

        claimed = await db.run(calendar_work.claim_calendar_work_item, db, "test-worker-1")

        assert claimed is not None
        item, event = claimed
        assert event["id"] == event_id
        assert item["action"] == "upsert"
        assert item["attempts"] == 1
        assert factory.row("calendar_work_items", item["id"])["status"] == "processing"

    async def test_complete_event_sync_updates_status(self, db, factory, calendar_user):
        """Test that completing event sync updates status correctly."""
        from selko.db import calendar_work

        event_id = self._queued_event(db, factory, calendar_user)
        item, _ = calendar_work.claim_calendar_work_item(db, "test-worker")

        assert calendar_work.complete_calendar_work(
            db, item["id"], "test-worker", item["generation"], "google-event-123"
        ) is True

        event = factory.row("events", event_id)
        assert event["review_status"] == "active"
        assert event["google_calendar_event_id"] == "google-event-123"
        assert event["synced_at"] is not None

    async def test_fail_event_sync_with_retry(self, db, factory, calendar_user):
        """Test that failing event sync allows retry."""
        from selko.db import calendar_work

        # The work item owns the retry budget.
        event_id = self._queued_event(db, factory, calendar_user)
        item, _ = calendar_work.claim_calendar_work_item(db, "worker-1")
        assert calendar_work.fail_calendar_work(
            db, item["id"], "worker-1", item["generation"],
            "calendar_sync_failed", "Test sync error",
        ) == {"fenced": False, "status": "pending"}

        assert factory.row("events", event_id)["review_status"] == "active"
        work_item = factory.row("calendar_work_items", item["id"])
        assert work_item["status"] == "pending"
        assert work_item["failure_code"] == "calendar_sync_failed"
        assert work_item["failure_detail"] == "Test sync error"
        assert work_item["locked_by"] is None
        assert work_item["next_retry_at"] is not None

    async def test_concurrent_workers_no_duplicate_event_sync(self, db, factory, calendar_user):
        """Concurrent claims through the single writer never share an item."""
        from selko.db import calendar_work

        self._queued_event(db, factory, calendar_user)

        claims = await asyncio.gather(*(
            db.run(calendar_work.claim_calendar_work_item, db, f"worker-{i}") for i in range(4)
        ))

        assert sum(claim is not None for claim in claims) == 1

    async def test_claim_excludes_users_without_active_calendar_integration(self, db, factory, calendar_user):
        """An expired google_calendar integration must not be claimed for sync.

        Otherwise workers keep burning attempts toward dead-letter on a user
        who is already known to need reauthorization.
        """
        from selko.db import calendar_work

        with db.write() as tx:
            tx.execute(
                "UPDATE integrations SET status = 'expired' WHERE user_id = ? AND provider = 'google_calendar'",
                (calendar_user,),
            )
        event_id = self._queued_event(db, factory, calendar_user, "Blocked on expired calendar auth")

        assert calendar_work.claim_calendar_work_item(db, "worker-1") is None
        row = db.query_one("SELECT status, attempts FROM calendar_work_items WHERE event_id = ?", (event_id,))
        assert (row["status"], row["attempts"]) == ("pending", 0)

    async def test_multiple_workers_get_different_events(self, db, factory, calendar_user):
        """Test that multiple workers claim different events."""
        from selko.db import calendar_work

        event_ids = [
            self._queued_event(db, factory, calendar_user, f"Test Event {i}", "pending_review")
            for i in range(3)
        ]

        claims = await asyncio.gather(*(
            db.run(calendar_work.claim_calendar_work_item, db, f"worker-{i}") for i in range(3)
        ))

        claimed_ids = {event["id"] for _, event in claims}
        assert claimed_ids == set(event_ids)
        assert {item["locked_by"] for item, _ in claims} == {"worker-0", "worker-1", "worker-2"}


@pytest.mark.integration
class TestCalendarSyncWorker:
    """Tests for calendar_sync worker on a real SQLite database with mocked Google API."""

    @pytest.mark.asyncio
    async def test_processes_approved_event(self, db, factory):
        """Test that calendar_sync worker processes an approved event."""
        from selko.workers.calendar_sync import sync_event

        user_id = factory.user()
        factory.integration(user_id, provider="google_calendar")
        event_id = factory.event(
            user_id, review_status="active", title="Worker Test Event",
            start_datetime="2026-05-01T14:00:00.000000Z",
            end_datetime="2026-05-01T15:00:00.000000Z",
        )
        event = factory.row("events", event_id)

        with patch("selko.services.calendars.get_credentials") as mock_creds, \
             patch("selko.services.calendars.build") as mock_build:

            mock_creds.return_value = MagicMock()
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            mock_service.events.return_value.list.return_value.execute.return_value = {"items": []}
            mock_service.events.return_value.insert.return_value.execute.return_value = {
                "id": "google-worker-test-123"
            }

            google_event_id = await sync_event(db, MagicMock(), event)

        assert google_event_id == "google-worker-test-123"
        body = mock_service.events.return_value.insert.call_args.kwargs["body"]
        assert body["summary"] == "Worker Test Event"
        log = db.query("SELECT action FROM calendar_sync_log WHERE event_id = ?", (event_id,))
        assert [r["action"] for r in log] == ["created"]


@pytest.mark.integration
class TestEmailProcessWorker:
    """The email_process worker with a mocked LLM gateway, on the real database."""

    @pytest.mark.asyncio
    async def test_processes_email_for_events(self, db, factory, mock_config):
        from selko.workers.email_process import process_email

        user_id = factory.user()
        email_id = _pending_email(
            factory, user_id, subject="Birthday Party Invitation",
            snippet="You're invited to Jake's birthday party on May 20th at 2pm!",
        )
        email = factory.row("emails", email_id)

        # The worker builds its gateway via create_llm_gateway(); the extraction
        # itself (another service) receives the database and the claimed row.
        with patch("selko.workers.email_process.create_llm_gateway", return_value=MagicMock()), \
             patch("selko.workers.email_process.process_email_for_events",
                   return_value={"num_events": 0, "num_new": 0, "num_updated": 0}) as extract:
            result = await process_email(db, mock_config, email)

        assert result["num_events"] == 0
        args = extract.call_args.args
        assert args[0] is db
        assert (args[2], args[3]) == (email_id, user_id)
        assert args[5]["id"] == email_id


@pytest.mark.integration
class TestWorkerConcurrency:
    """Concurrent worker behaviour over the single writer."""

    async def test_multiple_workers_get_different_emails(self, db, factory):
        user_id = factory.user()
        email_ids = {_pending_email(factory, user_id, subject=f"Test Email {i}") for i in range(3)}

        results = await asyncio.gather(*(claim_pending_email(db, f"worker-{i}") for i in range(3)))

        claimed = {r["id"]: r["locked_by"] for r in results if r}
        assert set(claimed) == email_ids
        assert len(set(claimed.values())) == 3
