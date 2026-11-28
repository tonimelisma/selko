"""The lease-fenced extraction commit, end to end on a real SQLite database.

Emails are claimed with the real `claim_unprocessed_email`, decisions are
committed with the real `commit_email_extraction`, and concurrent commits run on
real threads against the one writer. Ran against local Supabase before the
SQLite move; the node ids are kept.
"""

import asyncio
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from selko.db import emails as db_emails
from selko.db import events as db_events
from selko.services.events import find_matching_event
from selko.services.resolution_fingerprint import candidate_fingerprint
from tests.event_pipeline import providers_offline

EMPTY = candidate_fingerprint([])


def _claim(db, factory, user_id, worker_id: str) -> dict:
    """Insert a pending email and claim it as ``worker_id`` (the oldest claimable goes first)."""
    email_id = factory.email(user_id, subject="fenced extraction test")
    row = db_emails.claim_unprocessed_email(db, worker_id, 300)
    assert row is not None and row["id"] == email_id, "the test email is the only claimable one"
    return row


def _window(day: str) -> tuple[str, str]:
    y, m, d = (int(p) for p in day.split("-"))
    return f"{day}T00:00:00Z", f"{(date(y, m, d) + timedelta(days=1)).isoformat()}T00:00:00Z"


def _create(email_id, title: str, window: tuple[str, str], fingerprint: str = EMPTY) -> dict:
    return {
        "action": "create",
        "event_id": None,
        "intent": "no_change",
        "window_start": window[0],
        "window_end": window[1],
        "expected_fingerprint": fingerprint,
        "fields": {
            "title": title,
            "start_datetime": f"{window[0][:10]}T10:00:00Z",
            "end_datetime": f"{window[0][:10]}T11:00:00Z",
            "review_status": "pending_review",
        },
        "source": {"email_id": str(email_id), "extracted_data": {}},
    }


def _commit(db, row: dict, decisions: list[dict], *, worker=None, generation=None) -> dict:
    return db_events.commit_email_extraction(
        db, row["id"], worker or row["locked_by"],
        row["lock_generation"] if generation is None else generation, decisions, "processed",
    )


def _count(db, sql, params=()):
    return db.query_one(sql, params)[0]


def test_stale_generation_cannot_write(db, factory):
    user = factory.user()
    first = _claim(db, factory, user, "old-worker")
    # The lease expires and a new worker reclaims the email.
    with db.write() as tx:
        tx.execute("UPDATE emails SET locked_until = ? WHERE id = ?", (tx.ts(-1), first["id"]))
    second = db_emails.claim_unprocessed_email(db, "new-worker", 300)
    assert second["id"] == first["id"] and second["lock_generation"] == first["lock_generation"] + 1

    result = _commit(db, first, [_create(first["id"], "must not exist", _window("2031-01-03"))])

    assert result == {"fenced": True, "applied": 0}
    assert _count(db, "SELECT count(*) FROM events WHERE title = 'must not exist'") == 0
    assert factory.row("emails", first["id"])["locked_by"] == "new-worker"


def test_multi_event_email_commits_all_or_nothing(db, factory):
    user = factory.user()
    row = _claim(db, factory, user, "multi")
    bad = _create(row["id"], "bad", _window("2031-01-05"))
    bad["fields"]["review_status"] = "not-a-status"

    with pytest.raises(Exception):
        _commit(db, row, [_create(row["id"], "good", _window("2031-01-04")), bad])

    assert _count(db, "SELECT count(*) FROM events WHERE user_id = ?", (user,)) == 0
    assert factory.row("emails", row["id"])["processing_status"] == "processing"


def test_zombie_generation_after_reclaim_writes_nothing(db, factory):
    user = factory.user()
    first = _claim(db, factory, user, "zombie")
    with db.write() as tx:
        tx.execute("UPDATE emails SET locked_until = ? WHERE id = ?", (tx.ts(-1), first["id"]))
    db_emails.unlock_expired_email_locks(db)
    second = db_emails.claim_unprocessed_email(db, "zombie", 300)
    assert second["id"] == first["id"]

    # Same worker name, previous generation: still fenced.
    result = _commit(db, first, [_create(first["id"], "zombie", _window("2031-01-06"))])

    assert result["fenced"] is True
    assert _count(db, "SELECT count(*) FROM events WHERE title = 'zombie'") == 0


# Validates: SEL-170
async def test_two_emails_same_day_produce_one_event(db, factory):
    user = factory.user()
    first = _claim(db, factory, user, "same-day-a")
    second = _claim(db, factory, user, "same-day-b")
    window = _window("2031-02-03")

    results = await asyncio.gather(
        db.run(_commit, db, first, [_create(first["id"], "same-day-a", window)]),
        db.run(_commit, db, second, [_create(second["id"], "same-day-b", window)]),
    )

    assert sorted(result.get("applied", 0) for result in results) == [0, 1]
    assert sum(bool(result.get("conflict")) for result in results) == 1
    assert _count(
        db, "SELECT count(*) FROM events WHERE user_id = ? AND start_datetime >= ? AND start_datetime < ?",
        (user, "2031-02-03T00:00:00.000000Z", "2031-02-04T00:00:00.000000Z"),
    ) == 1


async def test_two_emails_different_days_never_conflict(db, factory):
    user = factory.user()
    first = _claim(db, factory, user, "different-day-a")
    second = _claim(db, factory, user, "different-day-b")

    results = await asyncio.gather(
        db.run(_commit, db, first, [_create(first["id"], "different-day-a", _window("2031-03-03"))]),
        db.run(_commit, db, second, [_create(second["id"], "different-day-b", _window("2031-03-04"))]),
    )

    assert all(result.get("conflict") is not True for result in results)
    assert [result["applied"] for result in results] == [1, 1]


def test_stale_fingerprint_returns_conflict_and_mutates_nothing(db, factory):
    user = factory.user()
    winner = _claim(db, factory, user, "fingerprint-winner")
    loser = _claim(db, factory, user, "fingerprint-loser")
    window = _window("2031-04-03")

    assert _commit(db, winner, [_create(winner["id"], "winner", window)])["applied"] == 1
    result = _commit(db, loser, [_create(loser["id"], "loser", window)])

    assert result["conflict"] is True
    assert result["conflicting_indexes"] == [0]
    assert _count(db, "SELECT count(*) FROM events WHERE user_id = ? AND title = 'loser'", (user,)) == 0
    assert factory.row("emails", loser["id"])["processing_status"] == "processing"


def test_conflict_recomputed_fingerprint_matches_winner(db, factory):
    user = factory.user()
    winner = _claim(db, factory, user, "recompute-winner")
    loser = _claim(db, factory, user, "recompute-loser")
    window = _window("2031-04-04")

    event_id = _commit(db, winner, [_create(winner["id"], "winner", window)])["event_ids"][0]
    fingerprint = db_events.band_fingerprint(db, user, *window)
    result = _commit(db, loser, [{
        "action": "update",
        "event_id": event_id,
        "intent": "no_change",
        "window_start": window[0],
        "window_end": window[1],
        "expected_fingerprint": fingerprint,
        "fields": {"description": "winner plus loser", "review_status": "pending_review"},
        "source": {"email_id": loser["id"], "source_type": "update", "extracted_data": {}},
    }])

    assert result["conflict"] is not True
    assert result["applied"] == 1
    assert factory.row("events", event_id)["description"] == "winner plus loser"
    assert _count(db, "SELECT count(*) FROM event_sources WHERE event_id = ?", (event_id,)) == 2


# Validates: SEL-167
@pytest.mark.parametrize("touched_between", [False, True])
def test_python_and_sql_fingerprints_agree(db, factory, touched_between):
    """The decision-time and commit-time fingerprints are one function over the same rows.

    The producer (`find_matching_event`) fingerprints the band it read; the
    commit recomputes it inside the writer transaction. They agree on an
    unchanged band, and a row changed between the two makes the commit refuse.
    """
    user = factory.user()
    existing = factory.event(user, title="fingerprint", start_datetime="2031-05-03T10:00:00.000000Z")
    row = _claim(db, factory, user, "fingerprint")
    with providers_offline(), patch("selko.services.events.event_processing.compare_events", return_value=None):
        _, window = find_matching_event(
            db, MagicMock(), user, {"title": "other", "start_datetime": "2031-05-03T15:00:00Z"},
            user_timezone="UTC", with_window=True,
        )
    if touched_between:
        with db.write() as tx:
            tx.execute("UPDATE events SET description = 'moved', updated_at = ? WHERE id = ?",
                       (tx.now_text, existing))

    decision = _create(row["id"], "other", (window.window_start, window.window_end), window.fingerprint)
    result = _commit(db, row, [decision])

    assert bool(result.get("conflict")) is touched_between
    assert _count(db, "SELECT count(*) FROM events WHERE title = 'other'") == (0 if touched_between else 1)
