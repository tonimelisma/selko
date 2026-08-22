"""Real-Postgres proof that the extraction commit honours its decision intent.

Every test here executes ``commit_email_extraction`` itself. That is the whole
point: the Changes lane was silently auto-applied for the entire life of #332
because the unit suite stubs this function and the proposal integration suite
INSERTs proposal rows directly, so nothing had ever run it with a change_set.
"""

import json
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import asyncpg
import pytest


pytestmark = pytest.mark.integration

DAY = "2026-09-14"


def _window() -> tuple[str, str]:
    start = f"{DAY}T00:00:00Z"
    year, month, day_number = (int(part) for part in DAY.split("-"))
    end = date(year, month, day_number) + timedelta(days=1)
    return start, f"{end.isoformat()}T00:00:00Z"


def _change_set() -> dict:
    return {
        "kind": "material_update",
        "changes": [
            {"field": "location", "before": "Room A", "after": "Room B"},
        ],
    }


def _snapshot() -> dict:
    return {
        "title": "Standup",
        "start_datetime": f"{DAY}T10:00:00Z",
        "end_datetime": f"{DAY}T11:00:00Z",
        "all_day": False,
        "location": "Room A",
        "description": None,
        "importance": "action_required",
        "review_status": "active",
    }


async def _claim_email(pg_pool, user_id: str) -> tuple:
    """Insert an email and claim it, returning (id, worker_id, generation)."""
    email_id = uuid4()
    worker = f"intent-{email_id}"
    await pg_pool.execute(
        """
        INSERT INTO public.emails (id, user_id, provider_message_id, subject, processing_status, created_at)
        VALUES ($1, $2, $3, 'intent test', 'pending', $4)
        """,
        email_id,
        user_id,
        f"intent-{email_id}",
        datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    for _ in range(50):
        row = await pg_pool.fetchrow(
            "SELECT * FROM public.claim_unprocessed_email($1, $2)", worker, 300
        )
        if row is None:
            break
        if row["id"] == email_id:
            return email_id, worker, row["lock_generation"]
        await pg_pool.execute(
            "UPDATE public.emails SET processing_status = 'processed',"
            " locked_by = NULL, locked_until = NULL WHERE id = $1",
            row["id"],
        )
    pytest.fail(f"could not claim test email {email_id}")


async def _event(pg_pool, user_id: str, review_status: str) -> str:
    event_id = uuid4()
    await pg_pool.execute(
        """
        INSERT INTO public.events (id, user_id, title, start_datetime, end_datetime,
                                   location, importance, review_status)
        VALUES ($1, $2, 'Standup', $3, $4, 'Room A', 'action_required', $5)
        """,
        event_id,
        user_id,
        datetime.fromisoformat(f"{DAY}T10:00:00+00:00"),
        datetime.fromisoformat(f"{DAY}T11:00:00+00:00"),
        review_status,
    )
    return event_id


async def _fingerprint(pg_pool, user_id: str) -> str:
    window = _window()
    return await pg_pool.fetchval(
        """
        SELECT md5(COALESCE(string_agg(e.id::text || ':' || to_char(e.updated_at AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), ',' ORDER BY e.id), ''))
        FROM public.events e
        WHERE e.user_id = $1 AND e.start_datetime >= $2 AND e.start_datetime < $3
        """,
        user_id,
        datetime.fromisoformat(window[0].replace("Z", "+00:00")),
        datetime.fromisoformat(window[1].replace("Z", "+00:00")),
    )


async def _commit(pg_pool, email_id, worker, generation, decision: dict) -> dict:
    return json.loads(await pg_pool.fetchval(
        "SELECT public.commit_email_extraction($1, $2, $3, $4::jsonb, 'processed')",
        email_id,
        worker,
        generation,
        json.dumps([decision]),
    ))


async def _decision(pg_pool, user_id, email_id, event_id, **overrides) -> dict:
    window = _window()
    decision = {
        "action": "update",
        "event_id": str(event_id),
        "window_start": window[0],
        "window_end": window[1],
        "expected_fingerprint": await _fingerprint(pg_pool, user_id),
        "hints": [],
        "source": {"email_id": str(email_id), "extracted_data": {}},
    }
    decision.update(overrides)
    return decision


async def _proposals(pg_pool, event_id) -> list[dict]:
    rows = await pg_pool.fetch(
        "SELECT status, kind, change_set FROM public.event_change_proposals WHERE event_id = $1",
        event_id,
    )
    return [dict(row) for row in rows]


async def _work_items(pg_pool, event_id) -> list[dict]:
    rows = await pg_pool.fetch(
        "SELECT action, status, desired_event FROM public.calendar_work_items WHERE event_id = $1",
        event_id,
    )
    return [dict(row) for row in rows]


async def _event_row(pg_pool, event_id) -> dict:
    return dict(await pg_pool.fetchrow(
        "SELECT review_status, title, location FROM public.events WHERE id = $1", event_id
    ))


# --- the four intents ----------------------------------------------------


async def test_review_intent_holds_the_change_and_writes_no_calendar_work(pg_pool, temp_user):
    """The Changes lane: a pending proposal, an untouched event, no provider write."""
    user_id, _, _ = temp_user
    email_id, worker, generation = await _claim_email(pg_pool, user_id)
    event_id = await _event(pg_pool, user_id, "active")

    result = await _commit(pg_pool, email_id, worker, generation, await _decision(
        pg_pool, user_id, email_id, event_id,
        intent="review",
        fields={"review_status": "active"},
        source={
            "email_id": str(email_id),
            "extracted_data": {},
            "source_type": "update",
            "event_snapshot_before": _snapshot(),
            "change_set": _change_set(),
        },
    ))

    assert result["applied"] == 1
    proposals = await _proposals(pg_pool, event_id)
    assert [p["status"] for p in proposals] == ["pending"], (
        "a change held for review must produce a pending proposal"
    )
    event = await _event_row(pg_pool, event_id)
    assert event["review_status"] == "active"
    assert event["location"] == "Room A", "the proposal owns the change, not the event"
    assert await _work_items(pg_pool, event_id) == [], (
        "nothing may reach the user's calendar before they accept"
    )


async def test_apply_intent_applies_the_change_and_queues_calendar_work(pg_pool, temp_user):
    user_id, _, _ = temp_user
    email_id, worker, generation = await _claim_email(pg_pool, user_id)
    event_id = await _event(pg_pool, user_id, "active")

    await _commit(pg_pool, email_id, worker, generation, await _decision(
        pg_pool, user_id, email_id, event_id,
        intent="apply",
        fields={
            "review_status": "active",
            "calendar_action": "upsert",
            "title": "Standup",
            "start_datetime": f"{DAY}T10:00:00Z",
            "end_datetime": f"{DAY}T11:00:00Z",
            "location": "Room B",
        },
        source={
            "email_id": str(email_id),
            "extracted_data": {},
            "source_type": "update",
            "event_snapshot_before": _snapshot(),
            "change_set": _change_set(),
        },
    ))

    assert [p["status"] for p in await _proposals(pg_pool, event_id)] == ["applied"]
    assert (await _event_row(pg_pool, event_id))["location"] == "Room B"
    items = await _work_items(pg_pool, event_id)
    assert [item["action"] for item in items] == ["upsert"]
    assert items[0]["desired_event"] is not None
    assert json.loads(items[0]["desired_event"])["title"] == "Standup", (
        "the queued payload must carry real values, never a NULL-filled object"
    )


async def test_apply_intent_on_a_new_lane_event_queues_no_calendar_work(pg_pool, temp_user):
    """Absorbing newer information into an unapproved event is not a delivery."""
    user_id, _, _ = temp_user
    email_id, worker, generation = await _claim_email(pg_pool, user_id)
    event_id = await _event(pg_pool, user_id, "pending_review")

    await _commit(pg_pool, email_id, worker, generation, await _decision(
        pg_pool, user_id, email_id, event_id,
        intent="apply",
        fields={"review_status": "pending_review", "location": "Room B"},
        source={
            "email_id": str(email_id),
            "extracted_data": {},
            "source_type": "update",
            "event_snapshot_before": _snapshot(),
            "change_set": _change_set(),
        },
    ))

    event = await _event_row(pg_pool, event_id)
    assert event["review_status"] == "pending_review", "it stays in the New lane"
    assert event["location"] == "Room B"
    assert await _work_items(pg_pool, event_id) == []


@pytest.mark.parametrize("declined", ["rejected", "cancelled"])
async def test_record_only_leaves_a_declined_event_untouched(pg_pool, temp_user, declined):
    """review-queue-integrity 8.2: record the match, change nothing."""
    user_id, _, _ = temp_user
    email_id, worker, generation = await _claim_email(pg_pool, user_id)
    event_id = await _event(pg_pool, user_id, declined)

    await _commit(pg_pool, email_id, worker, generation, await _decision(
        pg_pool, user_id, email_id, event_id,
        intent="record_only",
        fields={},
        source={"email_id": str(email_id), "extracted_data": {}, "source_type": "update"},
    ))

    event = await _event_row(pg_pool, event_id)
    assert event["review_status"] == declined, "a declined event is never revived"
    assert event["location"] == "Room A"
    assert await _proposals(pg_pool, event_id) == []
    assert await _work_items(pg_pool, event_id) == []
    # Provenance still lands: that is what keeps the identity match working, and
    # therefore what keeps the decision terminal instead of producing duplicates.
    assert await pg_pool.fetchval(
        "SELECT count(*) FROM public.event_sources WHERE event_id = $1 AND email_id = $2",
        event_id, email_id,
    ) == 1


# --- fail-closed ---------------------------------------------------------


async def test_a_decision_without_an_intent_is_refused(pg_pool, temp_user):
    """The regression itself: silence must never mean 'apply and deliver'."""
    user_id, _, _ = temp_user
    email_id, worker, generation = await _claim_email(pg_pool, user_id)
    event_id = await _event(pg_pool, user_id, "active")

    decision = await _decision(
        pg_pool, user_id, email_id, event_id,
        fields={},
        source={
            "email_id": str(email_id),
            "extracted_data": {},
            "source_type": "update",
            "event_snapshot_before": _snapshot(),
            "change_set": _change_set(),
        },
    )
    with pytest.raises(asyncpg.exceptions.PostgresError, match="known intent"):
        await _commit(pg_pool, email_id, worker, generation, decision)


async def test_a_decision_without_a_review_status_is_refused(pg_pool, temp_user):
    user_id, _, _ = temp_user
    email_id, worker, generation = await _claim_email(pg_pool, user_id)
    event_id = await _event(pg_pool, user_id, "active")

    decision = await _decision(
        pg_pool, user_id, email_id, event_id, intent="no_change", fields={},
    )
    with pytest.raises(asyncpg.exceptions.PostgresError, match="explicit review_status"):
        await _commit(pg_pool, email_id, worker, generation, decision)


async def test_review_intent_requires_an_active_event(pg_pool, temp_user):
    """A pending proposal requires review_status 'active'; say so, don't guess."""
    user_id, _, _ = temp_user
    email_id, worker, generation = await _claim_email(pg_pool, user_id)
    event_id = await _event(pg_pool, user_id, "active")

    decision = await _decision(
        pg_pool, user_id, email_id, event_id,
        intent="review",
        fields={"review_status": "pending_review"},
        source={
            "email_id": str(email_id),
            "extracted_data": {},
            "source_type": "update",
            "event_snapshot_before": _snapshot(),
            "change_set": _change_set(),
        },
    )
    with pytest.raises(asyncpg.exceptions.PostgresError, match="requires review_status active"):
        await _commit(pg_pool, email_id, worker, generation, decision)


async def test_no_change_intent_cannot_carry_a_change_set(pg_pool, temp_user):
    user_id, _, _ = temp_user
    email_id, worker, generation = await _claim_email(pg_pool, user_id)
    event_id = await _event(pg_pool, user_id, "active")

    decision = await _decision(
        pg_pool, user_id, email_id, event_id,
        intent="no_change",
        fields={"review_status": "active"},
        source={
            "email_id": str(email_id),
            "extracted_data": {},
            "source_type": "update",
            "event_snapshot_before": _snapshot(),
            "change_set": _change_set(),
        },
    )
    with pytest.raises(asyncpg.exceptions.PostgresError, match="cannot carry a change_set"):
        await _commit(pg_pool, email_id, worker, generation, decision)


@pytest.mark.parametrize("declined", ["rejected", "cancelled"])
async def test_calendar_upsert_is_refused_for_a_declined_event(pg_pool, temp_user, declined):
    """The queue helper no longer resurrects; it fails closed."""
    user_id, _, _ = temp_user
    event_id = await _event(pg_pool, user_id, declined)
    with pytest.raises(asyncpg.exceptions.PostgresError, match="cannot queue calendar upsert"):
        await pg_pool.fetchval(
            "SELECT public._enqueue_calendar_work($1, $2, 'upsert', $3::jsonb, NULL, false)",
            event_id, user_id, json.dumps({"title": "Standup"}),
        )
    assert (await _event_row(pg_pool, event_id))["review_status"] == declined


async def test_queueing_calendar_work_does_not_change_the_review_decision(pg_pool, temp_user):
    """events.review_status owns the user decision; the queue helper does not.

    The helper used to promote pending_review/rejected/cancelled to 'active' on
    every call. One caller depended on that side effect and two others undid it
    immediately afterwards, which is how a declined event could be revived by
    something as unrelated as queueing a calendar write.
    """
    user_id, _, _ = temp_user
    event_id = await _event(pg_pool, user_id, "pending_review")
    await pg_pool.fetchval(
        "SELECT public._enqueue_calendar_work($1, $2, 'upsert', $3::jsonb, NULL, false)",
        event_id, user_id, json.dumps({"title": "Standup"}),
    )
    assert (await _event_row(pg_pool, event_id))["review_status"] == "pending_review"
    assert [item["action"] for item in await _work_items(pg_pool, event_id)] == ["upsert"]
