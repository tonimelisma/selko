"""C7: Broadcast fan-out collapse — one realtime message per transaction.

realtime.send does NOT deduplicate the way pg_notify does, so the per-row
triggers from 20260809000003 emitted one Broadcast message per row. This pins
that a 50-row bulk UPDATE in one transaction produces exactly ONE message for
the user's private topic, and that the transaction-local guard does not leak
between transactions.
"""

from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def fanout_user(admin_client, temp_user):
    """A temp user with an active google_calendar integration and 50 events."""
    user_id, _, _ = temp_user
    admin_client.table("integrations").insert({
        "user_id": user_id,
        "provider": "google_calendar",
        "status": "active",
        "access_token": "test-token",
    }).execute()
    for i in range(50):
        admin_client.table("events").insert({
            "user_id": user_id,
            "title": f"c7-fanout-{i}",
            "start_datetime": "2026-08-11T10:00:00Z",
            "end_datetime": "2026-08-11T11:00:00Z",
            "status": "pending_review",
        }).execute()
    yield user_id
    try:
        admin_client.table("events").delete().like("title", "c7-fanout-%").execute()
    except Exception:
        pass


async def _message_count(pg_pool, user_id: str) -> int:
    return await pg_pool.fetchval(
        "SELECT count(*) FROM realtime.messages"
        " WHERE topic = 'user:' || $1::text || ':selko-changes'",
        user_id,
    )


async def test_bulk_update_emits_one_broadcast_per_resource(pg_pool, fanout_user):
    """C7: 50 rows updated in one transaction must produce one message.

    Measured as a delta: seeding itself broadcasts once per insert.
    """
    user_id = fanout_user
    before = await _message_count(pg_pool, user_id)
    async with pg_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE public.events SET status = 'rejected'"
                " WHERE user_id = $1 AND status = 'pending_review'",
                user_id,
            )
    after = await _message_count(pg_pool, user_id)

    delta = after - before
    assert delta == 1, (
        f"expected exactly 1 broadcast for a 50-row transaction, got {delta}"
    )


async def test_distinct_transactions_emit_distinct_broadcasts(pg_pool, fanout_user):
    """The GUC guard must not leak between transactions on a pooled connection."""
    user_id = fanout_user
    before = await _message_count(pg_pool, user_id)
    async with pg_pool.acquire() as conn:
        for i in range(3):
            async with conn.transaction():
                await conn.execute(
                    "UPDATE public.events SET status = 'rejected'"
                    " WHERE user_id = $1 AND status = 'pending_review'"
                    " AND title = $2",
                    user_id, f"c7-fanout-{i}",
                )
    after = await _message_count(pg_pool, user_id)

    delta = after - before
    assert delta == 3, (
        f"expected one broadcast per transaction (3), got {delta}"
    )
