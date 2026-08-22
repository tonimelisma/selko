"""Live LISTEN/NOTIFY tests for WorkListener (C3).

Run against local Supabase. The triggers from 20260809000002 fire
``pg_notify('selko_work', payload)`` per work type; these prove the listener
receives them, survives a killed socket, collapses batches per transaction,
and that one notification still means one claim.
"""

import asyncio
import json
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
async def work_listener(development_config):
    from selko.services.pg import WorkListener

    listener = WorkListener(development_config)
    await listener.start()
    yield listener
    await listener.stop()


class TestWorkListenerLive:
    async def test_notify_sets_the_matching_event(self, work_listener):
        """A real NOTIFY on selko_work wakes the matching work-type event."""
        event = work_listener.event_for("event_approved")
        event.clear()
        async with work_listener._conn.transaction():
            await work_listener._conn.execute(
                "SELECT pg_notify('selko_work', 'event_approved')"
            )
        await asyncio.wait_for(event.wait(), timeout=5)
        assert work_listener.status()["connected"] is True

    async def test_h3_dead_socket_reconnects_and_still_delivers(
        self, work_listener, pg_pool
    ):
        """A silently dropped socket must be detected and reconnected.

        Terminate the listener's backend from the server side; the heartbeat
        loop notices the dead socket, reconnects (re-issuing LISTEN), and a
        later NOTIFY is still delivered. NOTE: this kills every
        application_name='selko-worker' backend, including pool connections —
        they reconnect lazily.
        """
        before = work_listener.status()["reconnects"]
        # Exclude the backend running this very query (it is also named
        # selko-worker) so the terminate does not kill itself mid-operation.
        await pg_pool.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
            " WHERE application_name = 'selko-worker' AND pid <> pg_backend_pid()"
        )
        # Shorten the heartbeat interval so the dead socket is noticed fast.
        # The loop floors the interval at 30s; that floor is deliberate, so
        # this poll simply waits long enough for one heartbeat cycle.
        work_listener.config.pg_listener_heartbeat_seconds = 30
        # The heartbeat task reads the interval once per iteration; force a
        # quick cycle by restarting it.
        work_listener._heartbeat_task.cancel()
        try:
            await work_listener._heartbeat_task
        except asyncio.CancelledError:
            pass
        work_listener._heartbeat_task = asyncio.create_task(
            work_listener._heartbeat_loop(), name="pg-work-listener-heartbeat"
        )

        for _ in range(90):
            status = work_listener.status()
            if status["reconnects"] > before and status["connected"]:
                break
            await asyncio.sleep(0.5)
        status = work_listener.status()
        assert status["reconnects"] > before, (
            "listener did not reconnect after backend kill"
        )
        assert status["connected"], "listener did not re-establish LISTEN"

        event = work_listener.event_for("item_pending")
        event.clear()
        async with work_listener._conn.transaction():
            await work_listener._conn.execute(
                "SELECT pg_notify('selko_work', 'item_pending')"
            )
        await asyncio.wait_for(event.wait(), timeout=5)

    async def test_durability_missed_notification_costs_latency_never_work(
        self, work_listener, pg_pool, development_config, temp_user
    ):
        """H2: work inserted while the listener is down is still claimable.

        The notification is a hint; the claim path reads the database. Claim
        the event without any NOTIFY arriving first.
        """
        from selko.services.events import claim_approved_event_for_sync

        user_id, _, _ = temp_user
        event_id = str(uuid4())
        await pg_pool.execute(
            "INSERT INTO public.integrations"
            " (user_id, provider, status, access_token)"
            " VALUES ($1, 'google_calendar', 'active', 'test-token')",
            user_id,
        )
        await pg_pool.execute(
            "INSERT INTO public.events"
            " (id, user_id, title, start_datetime, end_datetime, review_status)"
            " VALUES ($1, $2, 'durability probe', now() + interval '1 hour',"
            " now() + interval '2 hours', 'active')",
            event_id, user_id,
        )
        await pg_pool.fetchval(
            "SELECT public.enqueue_calendar_work($1, $2, 'upsert', $3::jsonb)",
            event_id, user_id, json.dumps({"title": "durability probe"}),
        )
        claimed = await claim_approved_event_for_sync(
            pg_pool, "c3-durability-worker", lock_duration_seconds=120
        )
        assert claimed is not None
        assert str(claimed["id"]) == event_id

    async def test_batch_collapse_one_notification_per_transaction(self, pg_pool, temp_user):
        """§3.1: 100 rows in one transaction produce exactly one NOTIFY."""
        from selko.services.email_ingestion import SyncClaim

        user_id, _, _ = temp_user
        integration_id = str(uuid4())
        await pg_pool.execute(
            "INSERT INTO public.integrations"
            " (id, user_id, provider, status, access_token)"
            " VALUES ($1, $2, 'gmail', 'active', 'test-token')",
            integration_id, user_id,
        )

        conn = await pg_pool.acquire()
        try:
            notifications = []

            def _count(connection, pid, channel, payload):
                notifications.append(payload)

            await conn.add_listener("selko_work", _count)
            # 100 items in ONE transaction -> one notification per payload.
            async with conn.transaction():
                for i in range(100):
                    await conn.execute(
                        "INSERT INTO public.email_ingestion_items"
                        " (integration_id, user_id, provider, provider_message_id,"
                        " acquisition_status)"
                        " VALUES ($1, $2, 'gmail', $3, 'pending')",
                        integration_id, user_id, f"c3-batch-{i}",
                    )
            await asyncio.sleep(1.0)
            await conn.remove_listener("selko_work", _count)
        finally:
            await pg_pool.release(conn)

        item_notifies = [p for p in notifications if p == "item_pending"]
        assert len(item_notifies) == 1, (
            f"expected exactly 1 notification for 100 rows, got {len(item_notifies)}"
        )

    async def test_d3_two_listeners_one_notification_one_claim(
        self, work_listener, development_config, pg_pool, temp_user
    ):
        """Two listeners, one notification, one claim — no double-processing."""
        from selko.services.pg import WorkListener
        from selko.services.events import claim_approved_event_for_sync

        user_id, _, _ = temp_user
        second = WorkListener(development_config)
        await second.start()
        event_id = str(uuid4())
        await pg_pool.execute(
            "INSERT INTO public.integrations"
            " (user_id, provider, status, access_token)"
            " VALUES ($1, 'google_calendar', 'active', 'test-token')",
            user_id,
        )
        await pg_pool.execute(
            "INSERT INTO public.events"
            " (id, user_id, title, start_datetime, end_datetime, review_status)"
            " VALUES ($1, $2, 'd3 probe', now() + interval '1 hour',"
            " now() + interval '2 hours', 'active')",
            event_id, user_id,
        )
        await pg_pool.fetchval(
            "SELECT public.enqueue_calendar_work($1, $2, 'upsert', $3::jsonb)",
            event_id, user_id, json.dumps({"title": "d3 probe"}),
        )
        async with pg_pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_notify('selko_work', 'event_approved')"
                )

        ev1 = work_listener.event_for("event_approved")
        ev2 = second.event_for("event_approved")
        await asyncio.wait_for(ev1.wait(), timeout=5)
        await asyncio.wait_for(ev2.wait(), timeout=5)

        claimed_1 = await claim_approved_event_for_sync(
            pg_pool, "c3-d3-worker-1", lock_duration_seconds=120
        )
        claimed_2 = await claim_approved_event_for_sync(
            pg_pool, "c3-d3-worker-2", lock_duration_seconds=120
        )
        assert claimed_1 is not None
        assert claimed_2 is None or str(claimed_2["id"]) != str(claimed_1["id"])
