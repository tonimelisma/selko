"""Real-Postgres proof for the C2 hint writer and hint read-set fence."""

import json
from datetime import datetime, timezone
from hashlib import md5
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


async def test_commit_writes_identity_hints_in_same_transaction(pg_pool, temp_user):
    user_id, _, _ = temp_user
    email_id = uuid4()
    worker = f"identity-{email_id}"
    value_hash = "a" * 64
    await pg_pool.execute(
        """
        INSERT INTO public.emails
            (id, user_id, email_provider, provider_message_id, thread_id,
             processing_status, locked_by, lock_generation, date_sent)
        VALUES ($1, $2, 'gmail', $3, 'thread-c2', 'processing', $4, 1, $5)
        """,
        email_id, user_id, f"identity-{email_id}", worker,
        datetime.now(timezone.utc),
    )
    decision = {
        "action": "create",
        "event_id": None,
        "window_start": "2035-01-02T00:00:00Z",
        "window_end": "2035-01-03T00:00:00Z",
        "expected_fingerprint": md5(b"").hexdigest(),
        "hint_keys": [f"ical_uid|{value_hash}|"],
        "expected_hint_fingerprint": md5(b"").hexdigest(),
        "hints": [{
            "kind": "ical_uid",
            "value_hash": value_hash,
            "recurrence_id": "",
            "strength": "authoritative",
            "sequence": 1,
            "dtstamp": "2035-01-01T12:00:00Z",
        }],
        "fields": {
            "title": "C2 identity event",
            "start_datetime": "2035-01-02T10:00:00Z",
            "end_datetime": "2035-01-02T11:00:00Z",
        },
        "source": {"email_id": str(email_id), "extracted_data": {}},
    }
    try:
        result = json.loads(await pg_pool.fetchval(
            "SELECT public.commit_email_extraction($1, $2, 1, $3::jsonb, 'processed')",
            email_id, worker, json.dumps([decision]),
        ))
        assert result["applied"] == 1
        event_id = result["event_ids"][0]
        hint = await pg_pool.fetchrow(
            "SELECT event_id, kind, value_hash, sequence, dtstamp FROM public.event_identity_hints WHERE event_id = $1",
            event_id,
        )
        assert str(hint["event_id"]) == event_id
        assert hint["kind"] == "ical_uid"
        assert hint["value_hash"] == value_hash
        assert hint["sequence"] == 1
        assert hint["dtstamp"].isoformat().startswith("2035-01-01T12:00:00")
    finally:
        await pg_pool.execute("DELETE FROM public.emails WHERE id = $1", email_id)
        await pg_pool.execute("DELETE FROM public.events WHERE user_id = $1 AND title = $2", user_id, "C2 identity event")


async def test_hint_lookup_is_part_of_the_commit_fence(pg_pool, temp_user):
    user_id, _, _ = temp_user
    existing_event_id = uuid4()
    existing_email_id = uuid4()
    email_id = uuid4()
    worker = f"identity-fence-{email_id}"
    value_hash = "b" * 64
    await pg_pool.execute(
        """
        INSERT INTO public.emails
            (id, user_id, provider_message_id, processing_status, locked_by, lock_generation)
        VALUES ($1, $2, $3, 'processing', $4, 1), ($5, $2, $6, 'processed', NULL, 0)
        """,
        email_id, user_id, f"identity-fence-{email_id}", worker,
        existing_email_id, f"identity-source-{existing_email_id}",
    )
    await pg_pool.execute(
        """
        INSERT INTO public.events (id, user_id, title, start_datetime, end_datetime, status)
        VALUES ($1, $2, 'outside local day', '2036-02-02T10:00:00Z', '2036-02-02T11:00:00Z', 'pending_review')
        """,
        existing_event_id, user_id,
    )
    await pg_pool.execute(
        """
        INSERT INTO public.event_identity_hints
            (user_id, event_id, source_email_id, kind, value_hash, strength)
        VALUES ($1, $2, $3, 'join_url', $4, 'supporting')
        """,
        user_id, existing_event_id, existing_email_id, value_hash,
    )
    decision = {
        "action": "create",
        "event_id": None,
        "window_start": "2036-02-03T00:00:00Z",
        "window_end": "2036-02-04T00:00:00Z",
        "expected_fingerprint": md5(b"").hexdigest(),
        "hint_keys": [f"join_url|{value_hash}|"],
        "expected_hint_fingerprint": md5(b"").hexdigest(),
        "hints": [{"kind": "join_url", "value_hash": value_hash, "strength": "supporting"}],
        "fields": {
            "title": "must be fenced",
            "start_datetime": "2036-02-03T10:00:00Z",
            "end_datetime": "2036-02-03T11:00:00Z",
        },
        "source": {"email_id": str(email_id), "extracted_data": {}},
    }
    try:
        result = json.loads(await pg_pool.fetchval(
            "SELECT public.commit_email_extraction($1, $2, 1, $3::jsonb, 'processed')",
            email_id, worker, json.dumps([decision]),
        ))
        assert result["conflict"] is True
        assert await pg_pool.fetchval(
            "SELECT count(*) FROM public.events WHERE title = 'must be fenced'"
        ) == 0
    finally:
        await pg_pool.execute("DELETE FROM public.emails WHERE id IN ($1, $2)", email_id, existing_email_id)
        await pg_pool.execute("DELETE FROM public.events WHERE id = $1", existing_event_id)
