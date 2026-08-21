"""Real-Postgres proof for the lease-fenced extraction commit."""

import json
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from selko.services.resolution_fingerprint import candidate_fingerprint

pytestmark = pytest.mark.integration


async def _claim_email(pg_pool, user_id: str, worker_id: str) -> dict:
    email_id = uuid4()
    await pg_pool.execute(
        """
        INSERT INTO public.emails (id, user_id, provider_message_id, subject, processing_status, created_at)
        VALUES ($1, $2, $3, $4, 'pending', $5)
        """,
        email_id,
        user_id,
        f"fenced-{email_id}",
        "fenced extraction test",
        datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    for _ in range(25):
        row = await pg_pool.fetchrow(
            "SELECT * FROM public.claim_unprocessed_email($1, $2)", worker_id, 300
        )
        if row is None:
            break
        if row["id"] == email_id:
            return {"id": email_id, "row": dict(row)}
        await pg_pool.execute(
            "UPDATE public.emails SET processing_status = 'processed', locked_by = NULL, locked_until = NULL WHERE id = $1",
            row["id"],
        )
    pytest.fail(f"could not claim test email {email_id}")


async def _reclaim_email(pg_pool, email_id, worker_id: str) -> dict:
    await pg_pool.fetchval("SELECT public.unlock_expired_email_locks()")
    for _ in range(25):
        row = await pg_pool.fetchrow(
            "SELECT * FROM public.claim_unprocessed_email($1, $2)", worker_id, 300
        )
        if row is None:
            break
        if row["id"] == email_id:
            return dict(row)
        await pg_pool.execute(
            "UPDATE public.emails SET processing_status = 'processed', locked_by = NULL, locked_until = NULL WHERE id = $1",
            row["id"],
        )
    pytest.fail(f"could not reclaim test email {email_id}")


async def _delete_email(pg_pool, email_id) -> None:
    await pg_pool.execute("DELETE FROM public.emails WHERE id = $1", email_id)


def _window(day: str) -> tuple[str, str]:
    start = f"{day}T00:00:00Z"
    year, month, day_number = (int(part) for part in day.split("-"))
    from datetime import date as date_cls, timedelta

    end = date_cls(year, month, day_number) + timedelta(days=1)
    return start, f"{end.isoformat()}T00:00:00Z"


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _create_decision(email_id, title: str, window: tuple[str, str], fingerprint: str) -> dict:
    return {
        "action": "create",
        "event_id": None,
        "window_start": window[0],
        "window_end": window[1],
        "expected_fingerprint": fingerprint,
        "fields": {
            "title": title,
            "start_datetime": f"{window[0][:10]}T10:00:00Z",
            "end_datetime": f"{window[0][:10]}T11:00:00Z",
        },
        "source": {"email_id": str(email_id), "extracted_data": {}},
    }


async def _commit(pool, email_id, worker: str, generation: int, decisions: list[dict]) -> dict:
    return json.loads(await pool.fetchval(
        "SELECT public.commit_email_extraction($1, $2, $3, $4::jsonb, 'processed')",
        email_id,
        worker,
        generation,
        json.dumps(decisions),
    ))


async def test_stale_generation_cannot_write(pg_pool, temp_user):
    user_id, _, _ = temp_user
    claimed = await _claim_email(pg_pool, user_id, "fenced-old-worker")
    old_generation = claimed["row"]["lock_generation"]
    email_id = claimed["id"]
    try:
        await pg_pool.execute(
            "UPDATE public.emails SET locked_until = now() - interval '1 second' WHERE id = $1",
            email_id,
        )
        replacement = await _reclaim_email(pg_pool, email_id, "fenced-new-worker")
        assert replacement["id"] == email_id
        result = json.loads(await pg_pool.fetchval(
            "SELECT public.commit_email_extraction($1, $2, $3, $4::jsonb, $5)",
            email_id,
            "fenced-old-worker",
            old_generation,
            json.dumps([{
                "action": "create",
                "event_id": None,
                "window_start": "2030-01-02T00:00:00Z",
                "window_end": "2030-01-03T00:00:00Z",
                "expected_fingerprint": candidate_fingerprint([]),
                "fields": {
                    "title": "must not exist",
                    "start_datetime": "2030-01-01T10:00:00Z",
                    "end_datetime": "2030-01-01T11:00:00Z",
                },
                "source": {"email_id": str(email_id), "extracted_data": {}},
            }]),
            "processed",
        ))
        assert result["fenced"] is True
        assert result["applied"] == 0
        count = await pg_pool.fetchval(
            "SELECT count(*) FROM public.events WHERE user_id = $1 AND title = 'must not exist'",
            user_id,
        )
        assert count == 0
    finally:
        await _delete_email(pg_pool, email_id)


async def test_multi_event_email_commits_all_or_nothing(pg_pool, temp_user):
    user_id, _, _ = temp_user
    claimed = await _claim_email(pg_pool, user_id, "atomic-worker")
    email_id = claimed["id"]
    title = f"atomic-{email_id}"
    decisions = [
        {
            "action": "create",
            "event_id": None,
            "window_start": "2030-01-02T00:00:00Z",
            "window_end": "2030-01-03T00:00:00Z",
            "expected_fingerprint": candidate_fingerprint([]),
            "fields": {
                "title": title,
                "start_datetime": "2030-01-02T10:00:00Z",
                "end_datetime": "2030-01-02T11:00:00Z",
            },
            "source": {"email_id": str(email_id), "extracted_data": {}},
        },
        {"action": "invalid", "event_id": None, "fields": {}, "source": {}},
    ]
    try:
        with pytest.raises(Exception, match="invalid extraction decision envelope"):
            await pg_pool.fetchval(
                "SELECT public.commit_email_extraction($1, $2, $3, $4::jsonb, $5)",
                email_id,
                "atomic-worker",
                claimed["row"]["lock_generation"],
                json.dumps(decisions),
                "processed",
            )
        assert await pg_pool.fetchval(
            "SELECT count(*) FROM public.events WHERE user_id = $1 AND title = $2",
            user_id,
            title,
        ) == 0
        status = await pg_pool.fetchval(
            "SELECT processing_status FROM public.emails WHERE id = $1", email_id
        )
        assert status == "processing"
    finally:
        await _delete_email(pg_pool, email_id)


async def test_zombie_generation_after_reclaim_writes_nothing(pg_pool, temp_user):
    """A reclaimed lease rejects the late result exactly like a timed-out thread."""
    user_id, _, _ = temp_user
    claimed = await _claim_email(pg_pool, user_id, "zombie-worker")
    email_id = claimed["id"]
    try:
        await pg_pool.execute(
            "UPDATE public.emails SET locked_until = now() - interval '1 second' WHERE id = $1",
            email_id,
        )
        replacement = await _reclaim_email(pg_pool, email_id, "replacement-worker")
        assert replacement["id"] == email_id
        result = json.loads(await pg_pool.fetchval(
            "SELECT public.commit_email_extraction($1, $2, $3, '[]'::jsonb, 'processed')",
            email_id,
            "zombie-worker",
            claimed["row"]["lock_generation"],
        ))
        assert result["fenced"] is True
        assert await pg_pool.fetchval(
            "SELECT processing_status FROM public.emails WHERE id = $1", email_id
        ) == "processing"
    finally:
        await _delete_email(pg_pool, email_id)


async def test_two_emails_same_day_produce_one_event(pg_pool, temp_user):
    user_id, _, _ = temp_user
    first = await _claim_email(pg_pool, user_id, "same-day-a")
    second = await _claim_email(pg_pool, user_id, "same-day-b")
    window = _window("2031-02-03")
    empty = candidate_fingerprint([])
    try:
        results = await asyncio.gather(
            _commit(
                pg_pool, first["id"], "same-day-a",
                first["row"]["lock_generation"],
                [_create_decision(first["id"], "same-day-a", window, empty)],
            ),
            _commit(
                pg_pool, second["id"], "same-day-b",
                second["row"]["lock_generation"],
                [_create_decision(second["id"], "same-day-b", window, empty)],
            ),
        )
        assert sorted(result.get("applied", 0) for result in results) == [0, 1]
        assert sum(bool(result.get("conflict")) for result in results) == 1
        assert await pg_pool.fetchval(
            "SELECT count(*) FROM public.events WHERE user_id = $1 AND start_datetime >= $2::timestamptz AND start_datetime < $3::timestamptz",
                user_id, _instant(window[0]), _instant(window[1]),
        ) == 1
    finally:
        await _delete_email(pg_pool, first["id"])
        await _delete_email(pg_pool, second["id"])
        await pg_pool.execute(
            "DELETE FROM public.events WHERE user_id = $1 AND start_datetime >= $2::timestamptz AND start_datetime < $3::timestamptz",
                user_id, _instant(window[0]), _instant(window[1]),
        )


async def test_two_emails_different_days_never_conflict(pg_pool, temp_user):
    user_id, _, _ = temp_user
    first = await _claim_email(pg_pool, user_id, "different-day-a")
    second = await _claim_email(pg_pool, user_id, "different-day-b")
    first_window = _window("2031-03-03")
    second_window = _window("2031-03-04")
    try:
        results = await asyncio.gather(
            _commit(pg_pool, first["id"], "different-day-a", first["row"]["lock_generation"],
                    [_create_decision(first["id"], "different-day-a", first_window, candidate_fingerprint([]))]),
            _commit(pg_pool, second["id"], "different-day-b", second["row"]["lock_generation"],
                    [_create_decision(second["id"], "different-day-b", second_window, candidate_fingerprint([]))]),
        )
        assert all(result.get("conflict") is not True for result in results)
        assert [result["applied"] for result in results] == [1, 1]
    finally:
        await _delete_email(pg_pool, first["id"])
        await _delete_email(pg_pool, second["id"])
        await pg_pool.execute(
            "DELETE FROM public.events WHERE user_id = $1 AND start_datetime >= $2::timestamptz AND start_datetime < $3::timestamptz",
                user_id, _instant(first_window[0]), _instant(second_window[1]),
        )


async def test_stale_fingerprint_returns_conflict_and_mutates_nothing(pg_pool, temp_user):
    user_id, _, _ = temp_user
    winner = await _claim_email(pg_pool, user_id, "fingerprint-winner")
    loser = await _claim_email(pg_pool, user_id, "fingerprint-loser")
    window = _window("2031-04-03")
    try:
        assert (await _commit(
            pg_pool, winner["id"], "fingerprint-winner",
            winner["row"]["lock_generation"],
            [_create_decision(winner["id"], "winner", window, candidate_fingerprint([]))],
        ))["applied"] == 1
        result = await _commit(
            pg_pool, loser["id"], "fingerprint-loser",
            loser["row"]["lock_generation"],
            [_create_decision(loser["id"], "loser", window, candidate_fingerprint([]))],
        )
        assert result["conflict"] is True
        assert await pg_pool.fetchval(
            "SELECT count(*) FROM public.events WHERE user_id = $1 AND title = 'loser'", user_id
        ) == 0
    finally:
        await _delete_email(pg_pool, winner["id"])
        await _delete_email(pg_pool, loser["id"])
        await pg_pool.execute("DELETE FROM public.events WHERE user_id = $1", user_id)


async def test_conflict_recomputed_fingerprint_matches_winner(pg_pool, temp_user):
    user_id, _, _ = temp_user
    winner = await _claim_email(pg_pool, user_id, "recompute-winner")
    loser = await _claim_email(pg_pool, user_id, "recompute-loser")
    window = _window("2031-04-04")
    try:
        winner_result = await _commit(
            pg_pool,
            winner["id"],
            "recompute-winner",
            winner["row"]["lock_generation"],
            [_create_decision(winner["id"], "winner", window, candidate_fingerprint([]))],
        )
        event_id = winner_result["event_ids"][0]
        event_row = await pg_pool.fetchrow(
            "SELECT id, updated_at FROM public.events WHERE id = $1", event_id
        )
        fingerprint = candidate_fingerprint([dict(event_row)])
        result = await _commit(
            pg_pool,
            loser["id"],
            "recompute-loser",
            loser["row"]["lock_generation"],
            [{
                "action": "update",
                "event_id": str(event_id),
                "window_start": window[0],
                "window_end": window[1],
                "expected_fingerprint": fingerprint,
                "fields": {"description": "winner plus loser"},
                "source": {
                    "email_id": str(loser["id"]),
                    "source_type": "update",
                    "extracted_data": {},
                },
            }],
        )
        assert result["conflict"] is not True
        assert result["applied"] == 1
        assert await pg_pool.fetchval(
            "SELECT description FROM public.events WHERE id = $1", event_id
        ) == "winner plus loser"
        assert await pg_pool.fetchval(
            "SELECT count(*) FROM public.event_sources WHERE event_id = $1", event_id
        ) == 2
    finally:
        await _delete_email(pg_pool, winner["id"])
        await _delete_email(pg_pool, loser["id"])
        await pg_pool.execute("DELETE FROM public.events WHERE user_id = $1", user_id)


async def test_python_and_sql_fingerprints_agree(pg_pool, temp_user):
    user_id, _, _ = temp_user
    event_id = uuid4()
    try:
        await pg_pool.execute(
            "INSERT INTO public.events (id, user_id, title, start_datetime, end_datetime, review_status) VALUES ($1, $2, 'fingerprint', '2031-05-03T10:00:00Z', '2031-05-03T11:00:00Z', 'pending_review')",
            event_id, user_id,
        )
        rows = await pg_pool.fetch(
            "SELECT id, updated_at FROM public.events WHERE user_id = $1 AND start_datetime >= '2031-05-03T00:00:00Z' AND start_datetime < '2031-05-04T00:00:00Z'",
            user_id,
        )
        sql_value = await pg_pool.fetchval(
            "SELECT md5(COALESCE(string_agg(e.id::text || ':' || to_char(e.updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'), ',' ORDER BY e.id), '')) FROM public.events e WHERE e.user_id = $1 AND e.start_datetime >= '2031-05-03T00:00:00Z' AND e.start_datetime < '2031-05-04T00:00:00Z'",
            user_id,
        )
        assert candidate_fingerprint([dict(row) for row in rows]) == sql_value
    finally:
        await pg_pool.execute("DELETE FROM public.events WHERE id = $1", event_id)
