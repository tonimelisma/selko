"""selko.db.parked (Google Photos, parked) against a real SQLite database.

Ports the database behaviour of test_photos.py and test_scheduled_tasks.py for
the call sites that still have a caller, including the two startup unlocks.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from selko.db import parked
from selko.db.errors import CheckViolation, InvalidArgument, NotFound


def _photo(google_id="g-1", **extra):
    return {"google_photo_id": google_id, "filename": "IMG_1.jpg", "mime_type": "image/jpeg",
            "date_taken": "2026-07-04T18:30:00+02:00", "width": 4000, "height": 3000, **extra}


# --- photos ---------------------------------------------------------------------


def test_upsert_photo_inserts_and_returns_the_row(db, factory):
    user = factory.user()
    row = parked.upsert_photo(db, user, _photo())
    assert row["user_id"] == user
    assert row["google_photo_id"] == "g-1"
    assert row["date_taken"] == "2026-07-04T16:30:00.000000Z"
    assert row["processing_status"] == "pending"
    assert row["attempts"] == 0 and row["max_attempts"] == 3


def test_upsert_photo_updates_a_refetched_photo_in_place(db, factory):
    user = factory.user()
    first = parked.upsert_photo(db, user, _photo())
    parked.complete_photo(db, first["id"])
    again = parked.upsert_photo(db, user, _photo(filename="IMG_1_edited.jpg"))
    assert again["id"] == first["id"]
    assert again["filename"] == "IMG_1_edited.jpg"
    assert again["processing_status"] == "processed", "state the upsert did not name is kept"
    assert db.query_one("SELECT count(*) FROM photos")[0] == 1


def test_same_google_photo_for_two_users_is_two_rows(db, factory):
    alice, bob = factory.user(), factory.user()
    a = parked.upsert_photo(db, alice, _photo())
    b = parked.upsert_photo(db, bob, _photo())
    assert a["id"] != b["id"]


def test_upsert_photo_refuses_unknown_columns_and_missing_id(db, factory):
    user = factory.user()
    with pytest.raises(InvalidArgument):
        parked.upsert_photo(db, user, _photo(colour="red"))
    with pytest.raises(InvalidArgument):
        parked.upsert_photo(db, user, {"filename": "x"})


def test_get_photo_is_per_user(db, factory):
    alice, bob = factory.user(), factory.user()
    photo = parked.upsert_photo(db, alice, _photo())
    assert parked.get_photo(db, alice, photo["id"])["filename"] == "IMG_1.jpg"
    assert parked.get_photo(db, bob, photo["id"]) is None
    assert parked.get_photo(db, alice, "00000000-0000-4000-8000-000000000000") is None


def test_complete_photo_clears_the_lock(db, factory):
    user = factory.user()
    photo = parked.upsert_photo(db, user, _photo(processing_status="processing", locked_by="w1",
                                                  locked_until="2030-01-01T00:00:00Z"))
    assert parked.complete_photo(db, photo["id"]) == 1
    row = parked.get_photo(db, user, photo["id"])
    assert row["processing_status"] == "processed"
    assert row["processed_at"] is not None
    assert row["locked_by"] is None and row["locked_until"] is None


def test_fail_photo_retries_with_backoff(db, factory):
    user = factory.user()
    photo = parked.upsert_photo(db, user, _photo(attempts=2, processing_status="processing", locked_by="w1"))
    before = datetime.now(UTC)
    result = parked.fail_photo(db, photo["id"], "timeout")
    assert result == {"attempts": 2, "max_attempts": 3, "should_retry": True, "delay_seconds": 120}
    row = parked.get_photo(db, user, photo["id"])
    assert row["processing_status"] == "pending"
    assert row["processing_error"] == "timeout"
    assert row["locked_by"] is None
    retry_at = datetime.fromisoformat(row["next_retry_at"])
    assert timedelta(seconds=119) < retry_at - before < timedelta(seconds=125)
    assert row["dead_letter_at"] is None


def test_fail_photo_dead_letters_after_the_last_attempt(db, factory):
    user = factory.user()
    photo = parked.upsert_photo(db, user, _photo(attempts=3))
    result = parked.fail_photo(db, photo["id"], "corrupt")
    assert result["should_retry"] is False and result["delay_seconds"] is None
    row = parked.get_photo(db, user, photo["id"])
    assert row["processing_status"] == "failed"
    assert row["dead_letter_reason"] == "corrupt"
    assert row["dead_letter_at"] is not None


def test_fail_photo_unknown_raises(db):
    with pytest.raises(NotFound):
        parked.fail_photo(db, "00000000-0000-4000-8000-000000000000", "x")


def test_backoff_matches_retry_utils():
    from selko.services.retry_utils import calculate_retry_delay

    for attempt in range(1, 10):
        assert parked.retry_delay_seconds(attempt) == calculate_retry_delay(attempt)[0]


def test_unlock_expired_photo_locks(db, factory):
    user = factory.user()
    expired = parked.upsert_photo(db, user, _photo("g-1", processing_status="processing", locked_by="w",
                                                    locked_until="2020-01-01T00:00:00Z"))
    live = parked.upsert_photo(db, user, _photo("g-2", processing_status="processing", locked_by="w",
                                                 locked_until="2099-01-01T00:00:00Z"))
    parked.upsert_photo(db, user, _photo("g-3", processing_status="pending"))
    assert parked.unlock_expired_photo_locks(db) == 1
    assert parked.get_photo(db, user, expired["id"])["processing_status"] == "pending"
    assert parked.get_photo(db, user, expired["id"])["locked_by"] is None
    assert parked.get_photo(db, user, live["id"])["processing_status"] == "processing"
    assert parked.unlock_expired_photo_locks(db) == 0


# --- scheduled_tasks -----------------------------------------------------------


def test_enqueue_task_is_due_now_by_default(db, factory):
    user = factory.user()
    task_id = parked.enqueue_task(db, user, "photo_fetch", {"max_photos": 50})
    row = factory.row("scheduled_tasks", task_id)
    assert row["user_id"] == user
    assert row["status"] == "pending"
    assert row["payload"] == {"max_photos": 50}
    assert row["scheduled_at"] == row["created_at"]


def test_enqueue_task_at_a_time(db, factory):
    user = factory.user()
    when = datetime(2026, 12, 1, 9, 0, tzinfo=timezone(timedelta(hours=2)))
    task_id = parked.enqueue_task(db, user, "photo_fetch", {}, scheduled_at=when)
    assert factory.row("scheduled_tasks", task_id)["scheduled_at"] == "2026-12-01T07:00:00.000000Z"


def test_enqueue_task_refuses_unknown_types(db, factory):
    user = factory.user()
    with pytest.raises(InvalidArgument):
        parked.enqueue_task(db, user, "calendar_sync", {})


def test_task_type_check_holds_in_the_schema(db, factory):
    user = factory.user()
    with pytest.raises(CheckViolation), db.write() as tx:
        tx.execute("INSERT INTO scheduled_tasks (id, user_id, task_type) VALUES "
                   "('00000000-0000-4000-8000-000000000009', ?, 'other')", (user,))


def test_unlock_expired_scheduled_tasks(db, factory):
    user = factory.user()
    expired = parked.enqueue_task(db, user, "photo_fetch", {})
    live = parked.enqueue_task(db, user, "photo_fetch", {})
    with db.write() as tx:
        tx.execute("UPDATE scheduled_tasks SET status = 'processing', locked_by = 'w', locked_until = ? "
                   "WHERE id = ?", ("2020-01-01T00:00:00.000000Z", expired))
        tx.execute("UPDATE scheduled_tasks SET status = 'processing', locked_by = 'w', locked_until = ? "
                   "WHERE id = ?", ("2099-01-01T00:00:00.000000Z", live))
    assert parked.unlock_expired_scheduled_tasks(db) == 1
    row = factory.row("scheduled_tasks", expired)
    assert (row["status"], row["locked_by"], row["locked_until"]) == ("pending", None, None)
    assert factory.row("scheduled_tasks", live)["status"] == "processing"
    assert parked.unlock_expired_scheduled_tasks(db) == 0
