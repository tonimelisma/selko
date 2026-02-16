"""Unit tests for scheduled tasks service.

Tests the business logic functions in scheduled_tasks.py with mocked dependencies.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from selko.services.scheduled_tasks import (
    ScheduledTasksError,
    cleanup_old_scheduled_tasks,
    claim_scheduled_task,
    complete_scheduled_task,
    enqueue_scheduled_task,
    fail_scheduled_task,
    unlock_expired_scheduled_tasks,
)


class TestEnqueueScheduledTask:
    """Tests for enqueue_scheduled_task()."""

    def test_enqueue_without_scheduled_at(self):
        """Test enqueuing a task without explicit scheduled_at uses default."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        mock_result.data = [{"id": "task-uuid-123"}]
        mock_client.table.return_value.insert.return_value.execute.return_value = mock_result

        task_id = enqueue_scheduled_task(
            mock_client,
            user_id="user-123",
            task_type="email_fetch",
            payload={"max_emails": 50},
        )

        assert task_id == "task-uuid-123"

        # Verify insert was called with correct data (no scheduled_at)
        insert_call = mock_client.table.return_value.insert.call_args[0][0]
        assert insert_call["user_id"] == "user-123"
        assert insert_call["task_type"] == "email_fetch"
        assert insert_call["payload"] == {"max_emails": 50}
        assert "scheduled_at" not in insert_call

    def test_enqueue_with_scheduled_at(self):
        """Test enqueuing a task with explicit scheduled_at."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        mock_result.data = [{"id": "task-uuid-456"}]
        mock_client.table.return_value.insert.return_value.execute.return_value = mock_result

        scheduled_time = datetime(2026, 3, 15, 14, 0, 0)
        task_id = enqueue_scheduled_task(
            mock_client,
            user_id="user-123",
            task_type="email_fetch",
            payload={"max_emails": 100},
            scheduled_at=scheduled_time,
        )

        assert task_id == "task-uuid-456"

        # Verify insert included scheduled_at as ISO string
        insert_call = mock_client.table.return_value.insert.call_args[0][0]
        assert insert_call["scheduled_at"] == scheduled_time.isoformat()

    def test_enqueue_returns_uuid(self):
        """Test that enqueue returns the task UUID from the database."""
        mock_client = MagicMock()

        expected_uuid = "550e8400-e29b-41d4-a716-446655440000"
        mock_result = MagicMock()
        mock_result.data = [{"id": expected_uuid}]
        mock_client.table.return_value.insert.return_value.execute.return_value = mock_result

        result = enqueue_scheduled_task(
            mock_client,
            user_id="user-abc",
            task_type="email_fetch",
            payload={},
        )

        assert result == expected_uuid

    def test_enqueue_calls_correct_table(self):
        """Test that enqueue targets the scheduled_tasks table."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        mock_result.data = [{"id": "task-1"}]
        mock_client.table.return_value.insert.return_value.execute.return_value = mock_result

        enqueue_scheduled_task(
            mock_client,
            user_id="user-123",
            task_type="email_fetch",
            payload={},
        )

        mock_client.table.assert_called_with("scheduled_tasks")

    def test_enqueue_db_error_raises_scheduled_tasks_error(self):
        """Test that a database error raises ScheduledTasksError."""
        mock_client = MagicMock()
        mock_client.table.return_value.insert.return_value.execute.side_effect = (
            Exception("Connection refused")
        )

        with pytest.raises(ScheduledTasksError) as exc_info:
            enqueue_scheduled_task(
                mock_client,
                user_id="user-123",
                task_type="email_fetch",
                payload={},
            )

        assert "Failed to enqueue scheduled task" in str(exc_info.value)
        assert "Connection refused" in str(exc_info.value)


class TestClaimScheduledTask:
    """Tests for claim_scheduled_task()."""

    def test_claim_returns_task_when_available(self):
        """Test claiming returns a task dict when one is available."""
        mock_client = MagicMock()

        task_data = {
            "id": "task-123",
            "task_type": "email_fetch",
            "user_id": "user-456",
            "payload": {"max_emails": 50},
        }
        mock_result = MagicMock()
        mock_result.data = [task_data]
        mock_client.rpc.return_value.execute.return_value = mock_result

        result = claim_scheduled_task(
            mock_client,
            task_types=["email_fetch"],
            worker_id="worker-1",
        )

        assert result == task_data
        assert result["id"] == "task-123"
        assert result["task_type"] == "email_fetch"

    def test_claim_returns_none_when_no_tasks(self):
        """Test claiming returns None when no tasks are available."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        mock_result.data = []
        mock_client.rpc.return_value.execute.return_value = mock_result

        result = claim_scheduled_task(
            mock_client,
            task_types=["email_fetch"],
            worker_id="worker-1",
        )

        assert result is None

    def test_claim_passes_correct_rpc_params(self):
        """Test that claim passes correct parameters to the RPC call."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        mock_result.data = []
        mock_client.rpc.return_value.execute.return_value = mock_result

        claim_scheduled_task(
            mock_client,
            task_types=["email_fetch", "other_task"],
            worker_id="worker-abc",
            lock_duration_seconds=600,
        )

        mock_client.rpc.assert_called_once_with(
            "claim_next_scheduled_task",
            {
                "p_task_types": ["email_fetch", "other_task"],
                "p_worker_id": "worker-abc",
                "p_lock_duration_seconds": 600,
            },
        )

    def test_claim_db_error_raises_scheduled_tasks_error(self):
        """Test that a database error raises ScheduledTasksError."""
        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.side_effect = Exception("RPC failed")

        with pytest.raises(ScheduledTasksError) as exc_info:
            claim_scheduled_task(
                mock_client,
                task_types=["email_fetch"],
                worker_id="worker-1",
            )

        assert "Failed to claim scheduled task" in str(exc_info.value)


class TestCompleteScheduledTask:
    """Tests for complete_scheduled_task()."""

    def test_complete_updates_status_and_clears_lock(self):
        """Test completing a task sets status and clears lock fields."""
        mock_client = MagicMock()

        mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        complete_scheduled_task(mock_client, "task-123")

        # Verify update call
        update_call = mock_client.table.return_value.update.call_args[0][0]
        assert update_call["status"] == "completed"
        assert update_call["locked_by"] is None
        assert update_call["locked_until"] is None
        assert "completed_at" in update_call

        # Verify eq filter
        mock_client.table.return_value.update.return_value.eq.assert_called_with(
            "id", "task-123"
        )

    def test_complete_targets_correct_table(self):
        """Test that complete targets the scheduled_tasks table."""
        mock_client = MagicMock()

        mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        complete_scheduled_task(mock_client, "task-123")

        mock_client.table.assert_called_with("scheduled_tasks")

    def test_complete_db_error_raises_scheduled_tasks_error(self):
        """Test that a database error raises ScheduledTasksError."""
        mock_client = MagicMock()
        mock_client.table.return_value.update.return_value.eq.return_value.execute.side_effect = (
            Exception("Update failed")
        )

        with pytest.raises(ScheduledTasksError) as exc_info:
            complete_scheduled_task(mock_client, "task-123")

        assert "Failed to complete scheduled task" in str(exc_info.value)


class TestFailScheduledTask:
    """Tests for fail_scheduled_task()."""

    def test_fail_sets_status_error_and_clears_lock(self):
        """Test failing a task sets status, error, and clears lock fields."""
        mock_client = MagicMock()

        mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        fail_scheduled_task(mock_client, "task-123", "Connection timeout")

        # Verify update call
        update_call = mock_client.table.return_value.update.call_args[0][0]
        assert update_call["status"] == "failed"
        assert update_call["last_error"] == "Connection timeout"
        assert update_call["locked_by"] is None
        assert update_call["locked_until"] is None
        assert "completed_at" in update_call

    def test_fail_targets_correct_task(self):
        """Test that fail filters by the correct task ID."""
        mock_client = MagicMock()

        mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        fail_scheduled_task(mock_client, "task-xyz", "Some error")

        mock_client.table.return_value.update.return_value.eq.assert_called_with(
            "id", "task-xyz"
        )

    def test_fail_db_error_raises_scheduled_tasks_error(self):
        """Test that a database error raises ScheduledTasksError."""
        mock_client = MagicMock()
        mock_client.table.return_value.update.return_value.eq.return_value.execute.side_effect = (
            Exception("DB error")
        )

        with pytest.raises(ScheduledTasksError) as exc_info:
            fail_scheduled_task(mock_client, "task-123", "Original error")

        assert "Failed to update failed scheduled task" in str(exc_info.value)


class TestUnlockExpiredScheduledTasks:
    """Tests for unlock_expired_scheduled_tasks()."""

    def test_unlock_returns_count_when_tasks_unlocked(self):
        """Test that unlock returns the count of unlocked tasks."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        mock_result.data = 3
        mock_client.rpc.return_value.execute.return_value = mock_result

        count = unlock_expired_scheduled_tasks(mock_client)

        assert count == 3

    def test_unlock_returns_zero_when_none_expired(self):
        """Test that unlock returns zero when no tasks are expired."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        mock_result.data = 0
        mock_client.rpc.return_value.execute.return_value = mock_result

        count = unlock_expired_scheduled_tasks(mock_client)

        assert count == 0

    def test_unlock_handles_null_data(self):
        """Test that unlock returns zero when RPC returns null data."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        mock_result.data = None
        mock_client.rpc.return_value.execute.return_value = mock_result

        count = unlock_expired_scheduled_tasks(mock_client)

        assert count == 0

    def test_unlock_calls_correct_rpc(self):
        """Test that unlock calls the correct RPC function."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        mock_result.data = 0
        mock_client.rpc.return_value.execute.return_value = mock_result

        unlock_expired_scheduled_tasks(mock_client)

        mock_client.rpc.assert_called_once_with("unlock_expired_scheduled_tasks")

    def test_unlock_db_error_raises_scheduled_tasks_error(self):
        """Test that a database error raises ScheduledTasksError."""
        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.side_effect = Exception("RPC timeout")

        with pytest.raises(ScheduledTasksError) as exc_info:
            unlock_expired_scheduled_tasks(mock_client)

        assert "Failed to unlock expired scheduled tasks" in str(exc_info.value)


class TestCleanupOldScheduledTasks:
    """Tests for cleanup_old_scheduled_tasks()."""

    def test_cleanup_returns_count_of_deleted_tasks(self):
        """Test that cleanup returns the count of deleted tasks."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        mock_result.data = [{"id": "task-1"}, {"id": "task-2"}, {"id": "task-3"}]
        mock_client.table.return_value.delete.return_value.in_.return_value.lt.return_value.execute.return_value = mock_result

        count = cleanup_old_scheduled_tasks(mock_client)

        assert count == 3

    def test_cleanup_returns_zero_when_nothing_to_delete(self):
        """Test that cleanup returns zero when no old tasks exist."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        mock_result.data = []
        mock_client.table.return_value.delete.return_value.in_.return_value.lt.return_value.execute.return_value = mock_result

        count = cleanup_old_scheduled_tasks(mock_client)

        assert count == 0

    def test_cleanup_uses_correct_delete_chain(self):
        """Test that cleanup filters by status and completed_at cutoff."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        mock_result.data = []
        mock_delete = MagicMock()
        mock_in = MagicMock()
        mock_lt = MagicMock()

        mock_client.table.return_value.delete.return_value = mock_delete
        mock_delete.in_.return_value = mock_in
        mock_in.lt.return_value = mock_lt
        mock_lt.execute.return_value = mock_result

        cleanup_old_scheduled_tasks(mock_client, days_old=7)

        # Verify table
        mock_client.table.assert_called_with("scheduled_tasks")

        # Verify in_ filter for completed/failed statuses
        mock_delete.in_.assert_called_once_with("status", ["completed", "failed"])

        # Verify lt filter uses completed_at with a cutoff date
        lt_call_args = mock_in.lt.call_args
        assert lt_call_args[0][0] == "completed_at"
        # The cutoff should be an ISO format string
        cutoff_str = lt_call_args[0][1]
        assert isinstance(cutoff_str, str)

    def test_cleanup_custom_days_old(self):
        """Test that cleanup respects custom days_old parameter."""
        mock_client = MagicMock()

        mock_result = MagicMock()
        mock_result.data = []
        mock_delete = MagicMock()
        mock_in = MagicMock()
        mock_lt = MagicMock()

        mock_client.table.return_value.delete.return_value = mock_delete
        mock_delete.in_.return_value = mock_in
        mock_in.lt.return_value = mock_lt
        mock_lt.execute.return_value = mock_result

        with patch("selko.services.scheduled_tasks.datetime") as mock_datetime:
            fixed_now = datetime(2026, 3, 15, 12, 0, 0)
            mock_datetime.now.return_value = fixed_now
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

            cleanup_old_scheduled_tasks(mock_client, days_old=14)

            # Cutoff should be 14 days before fixed_now
            expected_cutoff = fixed_now - timedelta(days=14)
            lt_call_args = mock_in.lt.call_args
            assert lt_call_args[0][1] == expected_cutoff.isoformat()

    def test_cleanup_db_error_raises_scheduled_tasks_error(self):
        """Test that a database error raises ScheduledTasksError."""
        mock_client = MagicMock()
        mock_client.table.return_value.delete.return_value.in_.return_value.lt.return_value.execute.side_effect = (
            Exception("Delete failed")
        )

        with pytest.raises(ScheduledTasksError) as exc_info:
            cleanup_old_scheduled_tasks(mock_client)

        assert "Failed to cleanup scheduled tasks" in str(exc_info.value)
