"""Tests for the scheduled tasks service, over a real SQLite database.

Only enqueue and the startup unlock have callers. The claim, complete, fail
and cleanup wrappers had none and were not ported
(docs/specs/sqlite-single-process/02-data-layer.md §2.12 #62, §3.12), so their
tests went with them.
"""

import asyncio
from datetime import datetime, timezone

import pytest

from selko.services.scheduled_tasks import (
    ScheduledTasksError,
    enqueue_scheduled_task,
    unlock_expired_scheduled_tasks,
)


def _task(db, task_id):
    row = dict(db.query_one("SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)))
    return db.schema.decode("scheduled_tasks", row)


class TestEnqueueScheduledTask:
    def test_enqueue_without_scheduled_at_is_due_now(self, db, factory):
        user = factory.user()
        before = datetime.now(timezone.utc)
        task_id = enqueue_scheduled_task(db, user, "photo_fetch", {"max_photos": 100})
        task = _task(db, task_id)
        assert task["user_id"] == user
        assert task["task_type"] == "photo_fetch"
        assert task["status"] == "pending"
        assert task["payload"] == {"max_photos": 100}
        scheduled = datetime.fromisoformat(task["scheduled_at"].replace("Z", "+00:00"))
        assert abs((scheduled - before).total_seconds()) < 5

    def test_enqueue_with_scheduled_at(self, db, factory):
        when = datetime(2026, 3, 1, 9, 30, tzinfo=timezone.utc)
        task_id = enqueue_scheduled_task(db, factory.user(), "photo_fetch", {}, scheduled_at=when)
        assert _task(db, task_id)["scheduled_at"] == "2026-03-01T09:30:00.000000Z"

    def test_enqueue_returns_distinct_ids(self, db, factory):
        user = factory.user()
        assert enqueue_scheduled_task(db, user, "photo_fetch", {}) != enqueue_scheduled_task(
            db, user, "photo_fetch", {}
        )

    @pytest.mark.parametrize("bad", [
        {"user_id": "00000000-0000-0000-0000-000000000000", "task_type": "photo_fetch"},
        {"user_id": None, "task_type": "not_a_task"},
    ])
    def test_enqueue_db_error_raises_scheduled_tasks_error(self, db, factory, bad):
        user = bad["user_id"] or factory.user()
        with pytest.raises(ScheduledTasksError):
            enqueue_scheduled_task(db, user, bad["task_type"], {})


class TestUnlockExpiredScheduledTasks:
    def _processing(self, db, factory, offset_seconds):
        task_id = enqueue_scheduled_task(db, factory.user(), "photo_fetch", {})
        with db.write() as tx:
            tx.execute(
                "UPDATE scheduled_tasks SET status = 'processing', locked_by = 'w', locked_until = ? WHERE id = ?",
                (tx.ts(offset_seconds), task_id),
            )
        return task_id

    def test_unlock_returns_count_when_tasks_unlocked(self, db, factory):
        expired = self._processing(db, factory, -60)
        live = self._processing(db, factory, 600)
        assert asyncio.run(unlock_expired_scheduled_tasks(db)) == 1
        assert _task(db, expired)["status"] == "pending"
        assert _task(db, expired)["locked_by"] is None
        assert _task(db, live)["status"] == "processing"

    def test_unlock_returns_zero_when_none_expired(self, db):
        assert asyncio.run(unlock_expired_scheduled_tasks(db)) == 0

    def test_unlock_db_error_raises_scheduled_tasks_error(self):
        class Broken:
            async def run(self, *args, **kwargs):
                raise RuntimeError("disk gone")

        with pytest.raises(ScheduledTasksError):
            asyncio.run(unlock_expired_scheduled_tasks(Broken()))
