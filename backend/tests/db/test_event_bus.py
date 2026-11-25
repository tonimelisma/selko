"""Worker wake-ups and live hints on the in-process bus (05-verification.md §B.6).

Successor of integration/test_integration_work_listener.py and
integration/test_broadcast_fanout.py, which tested LISTEN/NOTIFY and
realtime.send on Postgres. The after-commit and rollback properties of the bus
itself are in test_sqlite_foundation.py
(`test_bus_delivers_after_commit_from_a_worker_thread`,
`test_live_hints_are_deduplicated_and_sent_after_commit`,
`test_rolled_back_write_sends_nothing`, `test_pending_email_wakes_the_email_worker`).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from selko.db import email_sync as es
from selko.services.email_ingestion import EmailIngestionRepository
from selko.workers.email_ingestion import EmailIngestionWorker


def _discovered_item(db, factory) -> str:
    user = factory.user()
    integration_id = factory.integration(user)
    with db.write() as tx:
        tx.execute("UPDATE email_sync_state SET next_poll_at = ? WHERE integration_id = ?",
                   (tx.ts(-60), integration_id))
    claim = es.claim_due_email_sync(db, "coordinator", 900)
    es.upsert_discovered_email_items(
        db, integration_id, claim["run_id"],
        [{"provider_message_id": "m-1", "provider_folder_ids": ["INBOX"], "change_kind": "upsert"}],
    )
    [row] = db.query("SELECT id FROM email_ingestion_items")
    return row["id"]


def test_a_discovered_item_wakes_the_acquisition_worker_after_commit(db, factory):
    async def scenario():
        await db.signals.start()
        event = db.signals.event_for("item_pending")
        event.clear()
        await asyncio.to_thread(_discovered_item, db, factory)
        await asyncio.wait_for(event.wait(), timeout=2)
        # By the time the wake-up fires the row is committed and claimable.
        assert db.query("SELECT 1 FROM email_ingestion_items WHERE acquisition_status = 'pending'")

    asyncio.run(scenario())


def test_one_invalidation_per_resource_per_transaction(db, factory):
    """A 50-row update in one transaction sends one hint per (user, resource)."""
    user = factory.user()
    for _ in range(50):
        factory.email(user)
    sent: list[tuple[str, dict]] = []
    original = db.bus.publish
    db.bus.publish = lambda topic, message: sent.append((topic, message)) or original(topic, message)
    try:
        with db.write() as tx:
            tx.execute("UPDATE emails SET processing_error = 'bulk' WHERE user_id = ?", (user,))
        with db.write() as tx:
            tx.execute("UPDATE emails SET processing_error = 'again' WHERE user_id = ?", (user,))
    finally:
        db.bus.publish = original

    email_hints = [m for topic, m in sent if topic == f"user:{user}" and m["resource"] == "emails"]
    assert len(email_hints) == 2, "one per transaction, never one per row"


def test_missed_wakeup_costs_latency_not_work(db, factory, mock_config):
    """With the wake-up dropped, the claim loop's floor still claims the row."""
    config = replace(mock_config, email_worker_idle_base_seconds=0.05, email_worker_idle_max_seconds=0.05)
    worker = EmailIngestionWorker(db, config, "acquirer", pg_pool=db, work_listener=db.signals)
    claimed: list[str] = []
    repository = EmailIngestionRepository(config, db)

    async def run_once():
        item = await repository.claim_item("acquirer")
        if item is None:
            return False
        claimed.append(item["id"])
        worker.stop()
        return True

    async def scenario():
        await db.signals.start()
        item_id = await asyncio.to_thread(_discovered_item, db, factory)
        db.signals.event_for("item_pending").clear()  # the notification is lost
        await asyncio.wait_for(worker._claim_loop(run_once, "item_pending"), timeout=5)
        return item_id

    item_id = asyncio.run(scenario())
    assert claimed == [item_id]
