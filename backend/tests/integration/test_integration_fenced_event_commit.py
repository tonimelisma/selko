"""Real-Postgres proof for the lease-fenced extraction commit."""

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

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
        with pytest.raises(Exception, match="invalid extraction decision action"):
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
