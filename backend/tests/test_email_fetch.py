"""Tests for email fetch scheduling deduplication."""

import pytest
from unittest.mock import MagicMock, patch

from selko.workers.email_fetch import schedule_email_fetches


class TestScheduleEmailFetches:
    """Tests for schedule_email_fetches() dedup logic."""

    @pytest.mark.asyncio
    async def test_skips_users_with_existing_pending_task(self):
        """Users with a pending email_fetch task are not re-enqueued."""
        mock_client = MagicMock()

        # User has active Gmail integration
        integrations_result = MagicMock()
        integrations_result.data = [{"user_id": "user-1", "provider": "gmail"}]

        # User already has a pending task
        existing_tasks_result = MagicMock()
        existing_tasks_result.data = [{"user_id": "user-1", "payload": {"provider": "gmail"}}]

        def table_side_effect(name):
            mock_table = MagicMock()
            if name == "integrations":
                mock_table.select.return_value.in_.return_value.eq.return_value.execute.return_value = integrations_result
            elif name == "scheduled_tasks":
                mock_table.select.return_value.eq.return_value.in_.return_value.execute.return_value = existing_tasks_result
            return mock_table

        mock_client.table.side_effect = table_side_effect

        with patch("selko.config.load_config"), \
             patch("selko.services.auth.get_service_client", return_value=mock_client), \
             patch("selko.workers.email_fetch.enqueue_scheduled_task") as mock_enqueue:
            await schedule_email_fetches()

            mock_enqueue.assert_not_called()

    @pytest.mark.asyncio
    async def test_enqueues_for_users_without_existing_task(self):
        """Users without an existing task get a new one enqueued."""
        mock_client = MagicMock()

        integrations_result = MagicMock()
        integrations_result.data = [{"user_id": "user-1", "provider": "gmail"}]

        # No existing tasks
        existing_tasks_result = MagicMock()
        existing_tasks_result.data = []

        def table_side_effect(name):
            mock_table = MagicMock()
            if name == "integrations":
                mock_table.select.return_value.in_.return_value.eq.return_value.execute.return_value = integrations_result
            elif name == "scheduled_tasks":
                mock_table.select.return_value.eq.return_value.in_.return_value.execute.return_value = existing_tasks_result
            return mock_table

        mock_client.table.side_effect = table_side_effect

        with patch("selko.config.load_config"), \
             patch("selko.services.auth.get_service_client", return_value=mock_client), \
             patch("selko.workers.email_fetch.enqueue_scheduled_task") as mock_enqueue:
            await schedule_email_fetches()

            mock_enqueue.assert_called_once_with(
                mock_client,
                user_id="user-1",
                task_type="email_fetch",
                payload={"user_id": "user-1", "provider": "gmail", "max_emails": 50},
            )

    @pytest.mark.asyncio
    async def test_mixed_users_some_with_existing_tasks(self):
        """Only users without existing tasks get new ones enqueued."""
        mock_client = MagicMock()

        integrations_result = MagicMock()
        integrations_result.data = [
            {"user_id": "user-1", "provider": "gmail"},
            {"user_id": "user-2", "provider": "gmail"},
            {"user_id": "user-3", "provider": "gmail"},
        ]

        # user-2 already has a pending task
        existing_tasks_result = MagicMock()
        existing_tasks_result.data = [{"user_id": "user-2", "payload": {"provider": "gmail"}}]

        def table_side_effect(name):
            mock_table = MagicMock()
            if name == "integrations":
                mock_table.select.return_value.in_.return_value.eq.return_value.execute.return_value = integrations_result
            elif name == "scheduled_tasks":
                mock_table.select.return_value.eq.return_value.in_.return_value.execute.return_value = existing_tasks_result
            return mock_table

        mock_client.table.side_effect = table_side_effect

        with patch("selko.config.load_config"), \
             patch("selko.services.auth.get_service_client", return_value=mock_client), \
             patch("selko.workers.email_fetch.enqueue_scheduled_task") as mock_enqueue:
            await schedule_email_fetches()

            assert mock_enqueue.call_count == 2
            enqueued_users = {call.kwargs["user_id"] for call in mock_enqueue.call_args_list}
            assert enqueued_users == {"user-1", "user-3"}

    @pytest.mark.asyncio
    async def test_no_users_with_gmail(self):
        """No tasks created when no users have active Gmail."""
        mock_client = MagicMock()

        integrations_result = MagicMock()
        integrations_result.data = []

        mock_client.table.return_value.select.return_value.in_.return_value.eq.return_value.execute.return_value = integrations_result

        with patch("selko.config.load_config"), \
             patch("selko.services.auth.get_service_client", return_value=mock_client), \
             patch("selko.workers.email_fetch.enqueue_scheduled_task") as mock_enqueue:
            await schedule_email_fetches()

            mock_enqueue.assert_not_called()
