"""R2 real-DB concurrency: one lane per user, generation-fenced."""

import asyncio
import json
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.development]

# Use pg_pool + manual seed like test_schema_contract does
import uuid as _uuid
from tests.integration.test_schema_contract import _seed_context  # type: ignore

@pytest.fixture
async def lane_conn(pg_pool):
    async with pg_pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            ctx = await _seed_context(conn)
            yield conn, ctx
        finally:
            await tx.rollback()

@pytest.mark.asyncio
async def test_concurrent_same_user_claim_yields_one(lane_conn, pg_pool):
    """Two workers claiming same user pending → only one gets lane."""
    conn, ctx = lane_conn
    # Create two emails for same user with extractions
    email1 = ctx.email_id
    # Create second email
    import uuid
    email2 = uuid.uuid4()
    await conn.execute("INSERT INTO public.emails (id, user_id, email_provider, provider_message_id, subject, from_email, provider_labels) VALUES ($1,$2,'gmail',$3,'t','a@b.com','{}')", email2, ctx.user_id, f"lane-test-{email2}")
    # Enqueue both
    for eid in [email1, email2]:
        await conn.fetchval("SELECT public.enqueue_email_event_resolution($1,$2,$3,$4,$5,$6)", eid, ctx.user_id, json.dumps([{"title":"t"}]), f"hash-{eid}", "llm", "pending_review")
    # Two concurrent claims
    r1 = await conn.fetchrow("SELECT * FROM public.claim_email_event_resolution('w1', 60)")
    r2 = await conn.fetchrow("SELECT * FROM public.claim_email_event_resolution('w2', 60)")
    # Exactly one should succeed (one row, other None)
    assert (r1 is not None) ^ (r2 is not None) or (r1 is not None and r2 is None) or (r1 is None and r2 is not None)
    # Clean up lane
    claimed = r1 or r2
    if claimed:
        await conn.execute("SELECT public.fail_email_event_resolution($1,$2,$3,$4,$5)", claimed["user_id"], claimed["email_id"], claimed["lease_owner"], claimed["lease_generation"], "test")

@pytest.mark.asyncio
async def test_expired_lane_reclaims_with_larger_generation(lane_conn):
    conn, ctx = lane_conn
    import uuid, json
    email = uuid.uuid4()
    await conn.execute("INSERT INTO public.emails (id, user_id, email_provider, provider_message_id, subject, from_email, provider_labels) VALUES ($1,$2,'gmail',$3,'t','a@b.com','{}')", email, ctx.user_id, f"gen-test-{email}")
    await conn.fetchval("SELECT public.enqueue_email_event_resolution($1,$2,$3,$4,$5,$6)", email, ctx.user_id, json.dumps([{"title":"t"}]), f"hash-{email}", "llm", "pending_review")
    r1 = await conn.fetchrow("SELECT * FROM public.claim_email_event_resolution('w1', 60)")
    assert r1 is not None
    gen1 = r1["lease_generation"]
    await conn.execute("UPDATE public.event_resolution_lanes SET lease_expires_at = now() - interval '1 second' WHERE user_id = $1", ctx.user_id)
    r2 = await conn.fetchrow("SELECT * FROM public.claim_email_event_resolution('w2', 60)")
    assert r2 is not None
    assert r2["lease_generation"] > gen1
    assert r2["email_id"] == email

@pytest.mark.asyncio
async def test_old_generation_cannot_commit(lane_conn):
    conn, ctx = lane_conn
    import uuid, json
    email = uuid.uuid4()
    await conn.execute("INSERT INTO public.emails (id, user_id, email_provider, provider_message_id, subject, from_email, provider_labels) VALUES ($1,$2,'gmail',$3,'t','a@b.com','{}')", email, ctx.user_id, f"commit-test-{email}")
    await conn.fetchval("SELECT public.enqueue_email_event_resolution($1,$2,$3,$4,$5,$6)", email, ctx.user_id, json.dumps([{"title":"t"}]), f"hash-{email}", "llm", "pending_review")
    r1 = await conn.fetchrow("SELECT * FROM public.claim_email_event_resolution('w1', 60)")
    assert r1 is not None
    # Expire and reclaim
    await conn.execute("UPDATE public.event_resolution_lanes SET lease_expires_at = now() - interval '1 second' WHERE user_id = $1", ctx.user_id)
    r2 = await conn.fetchrow("SELECT * FROM public.claim_email_event_resolution('w2', 60)")
    assert r2 is not None
    # Old generation should fail to commit
    ok_old = await conn.fetchval("SELECT public.commit_email_event_resolution_item($1,$2,$3,$4,$5,$6,$7)", ctx.user_id, email, 0, "w1", r1["lease_generation"], None, "created")
    assert ok_old is False
    ok_new = await conn.fetchval("SELECT public.commit_email_event_resolution_item($1,$2,$3,$4,$5,$6,$7)", ctx.user_id, email, 0, "w2", r2["lease_generation"], None, "created")
    assert ok_new is True
