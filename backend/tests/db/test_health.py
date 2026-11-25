"""selko.db.health.health_work_state against a real SQLite database.

Ports the work-state assertions of
integration/test_integration_ingestion_stall_signal.py,
integration/test_integration_email_state_machine.py (health tests) and
test_ingestion_runtime.py::test_health_snapshot_counts_1500_dead_letters_without_truncation.

Every degrading counter is shown going red and then back to green on its own
(CLAUDE.md, "Health signals must be able to return to green"). Each test has
its own fresh database, so the roll-up is decided only by the rows it makes.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from selko.db import health
from selko.db.codec import new_id, to_timestamp, utc_now


def ts(delta_seconds: float = 0) -> str:
    return to_timestamp(utc_now() + timedelta(seconds=delta_seconds))


def _set(db, table, key_col, key, **fields):
    cols = ", ".join(f"{k} = ?" for k in fields)
    with db.write() as tx:
        tx.execute(f"UPDATE {table} SET {cols} WHERE {key_col} = ?", (*fields.values(), key))


def _h(db, warning_seconds=3600):
    return health.health_work_state(db, warning_seconds)


@pytest.fixture
def user(factory):
    return factory.user()


@pytest.fixture
def quiet_integration(db, factory, user):
    """An active Gmail integration whose next poll is in the future (not due, not stale)."""
    integration_id = factory.integration(user, provider="gmail")
    _set(db, "email_sync_state", "integration_id", integration_id, next_poll_at=ts(600))
    return integration_id


def _item(factory, integration_id, user_id, **overrides):
    fields = {"id": new_id(), "integration_id": integration_id, "user_id": user_id,
              "provider": "gmail", "provider_message_id": f"stall-{new_id()}",
              "acquisition_status": "pending", "attempts": 0, "max_attempts": 8,
              "created_at": ts()}
    fields.update(overrides)
    return factory._insert("email_ingestion_items", fields)


def test_empty_database_is_ok_with_every_key(db):
    result = _h(db)
    assert tuple(result) == health.HEALTH_KEYS
    assert result["status"] == "ok"
    assert result["items_stalled_seconds"] is None
    assert result["oldest_next_poll_seconds"] is None
    assert all(result[k] == 0 for k in health.HEALTH_KEYS
               if k not in ("status", "items_stalled_seconds", "oldest_next_poll_seconds"))


# --- emails -----------------------------------------------------------------


def test_stale_processing_email_degrades_and_recovers(db, factory, user):
    email = factory.email(user, processing_status="processing", attempts=1,
                          locked_by="dead-worker", locked_until=ts(-3600))
    result = _h(db)
    assert result["stale_processing_emails"] == 1
    assert result["processing_emails"] == 1
    assert result["status"] == "degraded"

    _set(db, "emails", "id", email, processing_status="processed", locked_by=None, locked_until=None)
    result = _h(db)
    assert result["stale_processing_emails"] == 0
    assert result["status"] == "ok"


def test_health_counts_use_worker_claim_predicates(db, factory, user):
    factory.email(user, processing_status="pending", attempts=0, max_attempts=3)
    factory.email(user, processing_status="failed", attempts=3, max_attempts=3)
    factory.email(user, processing_status="processing", attempts=1, locked_by="worker",
                  locked_until=ts(3600))
    # Not ready: backing off, and waiting for an attachment.
    factory.email(user, processing_status="pending", next_retry_at=ts(600))
    waiting = factory.email(user, processing_status="pending")
    factory._insert("attachments", {"id": new_id(), "user_id": user, "email_id": waiting,
                                    "filename": "a.pdf", "ingestion_status": "retry"})

    result = _h(db)
    assert result["ready_emails"] == 1
    assert result["failed_emails"] == 1
    assert result["processing_emails"] == 1
    assert result["stale_processing_emails"] == 0


def test_terminal_failures_never_degrade(db, factory, user):
    """failed_emails is history: counted, but it must not pin the roll-up red."""
    for _ in range(3):
        factory.email(user, processing_status="failed", attempts=3, max_attempts=3)
    result = _h(db)
    assert result["failed_emails"] == 3
    assert result["unclaimable_pending"] == 0
    assert result["status"] == "ok"


def test_unclaimable_pending_degrades_and_recovers(db, factory, user):
    """The CHECK forbids a stored pending+exhausted row; only a broken invariant shows it.

    The violation is simulated with the CHECKs switched off for one statement.
    """
    email = factory.email(user, processing_status="pending", attempts=0, max_attempts=3)
    with db.write() as tx:
        tx.execute("PRAGMA ignore_check_constraints = ON")
        tx.execute("UPDATE emails SET attempts = 3 WHERE id = ?", (email,))
        tx.execute("PRAGMA ignore_check_constraints = OFF")
    result = _h(db)
    assert result["unclaimable_pending"] == 1
    assert result["ready_emails"] == 0
    assert result["failed_emails"] == 0
    assert result["status"] == "degraded"

    _set(db, "emails", "id", email, attempts=0)
    result = _h(db)
    assert result["unclaimable_pending"] == 0
    assert result["status"] == "ok"


# --- sync runs, leases, polls ---------------------------------------------------


def test_stale_sync_run_degrades_and_recovers(db, factory, user, quiet_integration):
    run = factory._insert("email_sync_runs", {"id": new_id(), "integration_id": quiet_integration,
                                              "user_id": user, "provider": "gmail",
                                              "run_kind": "incremental", "status": "running"})
    result = _h(db)
    assert result["stale_sync_runs"] == 1
    assert result["status"] == "degraded"

    # A live lease means the run is being worked: not stale.
    _set(db, "email_sync_state", "integration_id", quiet_integration,
         lease_owner="w", lease_expires_at=ts(300))
    result = _h(db)
    assert result["stale_sync_runs"] == 0
    assert result["leases_held"] == 1
    assert result["status"] == "ok"

    _set(db, "email_sync_state", "integration_id", quiet_integration,
         lease_owner=None, lease_expires_at=None)
    _set(db, "email_sync_runs", "id", run, status="completed")
    result = _h(db)
    assert result["stale_sync_runs"] == 0
    assert result["leases_held"] == 0
    assert result["status"] == "ok"


def test_overdue_poll_degrades_past_the_warning_and_recovers(db, factory, user, quiet_integration):
    _set(db, "email_sync_state", "integration_id", quiet_integration, next_poll_at=ts(-7200))
    result = _h(db, warning_seconds=3600)
    assert result["integrations_due"] == 1
    assert 7199 <= result["oldest_next_poll_seconds"] <= 7202
    assert result["status"] == "degraded"
    # Below the threshold it is reported but does not degrade.
    assert _h(db, warning_seconds=10**9)["status"] == "ok"

    _set(db, "email_sync_state", "integration_id", quiet_integration, next_poll_at=ts(600))
    result = _h(db)
    assert result["integrations_due"] == 0
    assert result["oldest_next_poll_seconds"] == 0  # future polls clamp to zero
    assert result["status"] == "ok"


def test_health_ignores_expired_integration_poll_age(db, factory, user, quiet_integration):
    before = _h(db)
    _set(db, "integrations", "id", quiet_integration, status="expired")
    _set(db, "email_sync_state", "integration_id", quiet_integration,
         next_poll_at="2000-01-01T00:00:00.000000Z")
    after = _h(db)
    assert after["status"] == before["status"] == "ok"
    assert after["oldest_next_poll_seconds"] is None
    assert after["integrations_due"] == 0


def test_a_leased_due_integration_is_not_counted_due(db, factory, user, quiet_integration):
    _set(db, "email_sync_state", "integration_id", quiet_integration, next_poll_at=ts(-10),
         lease_owner="w", lease_expires_at=ts(300))
    assert _h(db)["integrations_due"] == 0


# --- dead letters ---------------------------------------------------------------


def test_dead_letters_degrade_and_recover(db, factory, user, quiet_integration):
    item = _item(factory, quiet_integration, user, acquisition_status="dead_letter")
    email = factory.email(user, integration_id=quiet_integration, processing_status="processed")
    attachment = factory._insert("attachments", {"id": new_id(), "user_id": user, "email_id": email,
                                                 "filename": "a.pdf", "ingestion_status": "dead_letter"})
    result = _h(db)
    assert result["items_dead_letter"] == 1
    assert result["attachments_dead_letter"] == 1
    assert result["items_pending"] == 0
    assert result["status"] == "degraded"

    _set(db, "email_ingestion_items", "id", item, acquisition_status="completed")
    assert _h(db)["status"] == "degraded"  # the attachment still needs repair
    _set(db, "attachments", "id", attachment, ingestion_status="stored")
    result = _h(db)
    assert result["items_dead_letter"] == 0
    assert result["attachments_dead_letter"] == 0
    assert result["status"] == "ok"


def test_counts_1500_dead_letters_without_truncation(db, factory, user, quiet_integration):
    with db.write() as tx:
        for n in range(1500):
            tx.execute(
                "INSERT INTO email_ingestion_items (id, integration_id, user_id, provider, "
                "provider_message_id, acquisition_status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'gmail', ?, 'dead_letter', ?, ?)",
                (new_id(), quiet_integration, user, f"m-{n}", tx.now_text, tx.now_text),
            )
    result = _h(db)
    assert result["items_dead_letter"] == 1500
    assert result["status"] == "degraded"


# --- incidents ------------------------------------------------------------------


def test_open_email_sync_incident_degrades_and_recovers(db, factory, user, quiet_integration):
    incident = factory._insert("operational_incidents", {
        "id": new_id(), "incident_key": f"email-sync:{quiet_integration}:stale_poll",
        "integration_id": quiet_integration, "user_id": user, "incident_type": "stale_poll",
        "severity": "warning", "status": "open", "safe_summary": "stale"})
    # Another subsystem's incident, and a key differing only in case, do not count.
    factory._insert("operational_incidents", {
        "id": new_id(), "incident_key": "calendar:x", "incident_type": "t",
        "severity": "warning", "status": "open", "safe_summary": "s"})
    factory._insert("operational_incidents", {
        "id": new_id(), "incident_key": "EMAIL-SYNC:x", "incident_type": "t",
        "severity": "warning", "status": "open", "safe_summary": "s"})
    result = _h(db)
    assert result["open_incidents"] == 1
    assert result["status"] == "degraded"

    _set(db, "operational_incidents", "id", incident, status="resolved")
    result = _h(db)
    assert result["open_incidents"] == 0
    assert result["status"] == "ok"


# --- the ingestion stall signal -------------------------------------------------


class TestIngestionStallSignal:
    def test_a_frozen_backlog_degrades_the_rollup(self, db, factory, user, quiet_integration):
        _item(factory, quiet_integration, user, created_at=ts(-19 * 86400))
        result = _h(db, warning_seconds=3600)
        assert result["items_pending"] == 1
        assert result["items_dead_letter"] == 0
        assert result["items_stalled_seconds"] >= 19 * 86400 - 60
        # The threshold differential isolates this signal: nothing else degrades here.
        assert _h(db, warning_seconds=10**9)["status"] == "ok"
        assert _h(db, warning_seconds=3600)["status"] == "degraded"

    def test_an_in_flight_lease_means_draining_not_stalled(self, db, factory, user, quiet_integration):
        _item(factory, quiet_integration, user, created_at=ts(-19 * 86400))
        _item(factory, quiet_integration, user, acquisition_status="processing", attempts=1,
              lease_owner="worker-1", lease_expires_at=ts(900))
        result = _h(db)
        assert result["items_pending"] == 2
        assert result["items_stalled_seconds"] == 0
        assert result["status"] == "ok"

    def test_it_returns_to_green_when_the_backlog_drains(self, db, factory, user, quiet_integration):
        item = _item(factory, quiet_integration, user, created_at=ts(-19 * 86400))
        assert _h(db)["items_stalled_seconds"] is not None
        _set(db, "email_ingestion_items", "id", item, acquisition_status="completed", completed_at=ts())
        result = _h(db)
        assert result["items_stalled_seconds"] is None
        assert result["items_pending"] == 0
        assert result["status"] == "ok"

    def test_a_row_serving_its_retry_backoff_is_not_stalled(self, db, factory, user, quiet_integration):
        _item(factory, quiet_integration, user, acquisition_status="retry", attempts=1,
              created_at=ts(-19 * 86400), next_retry_at=ts(600))
        result = _h(db)
        assert result["items_pending"] == 1
        assert result["items_stalled_seconds"] is None

    def test_an_exhausted_row_is_not_counted_as_stalled(self, db, factory, user, quiet_integration):
        _item(factory, quiet_integration, user, attempts=8, max_attempts=8, created_at=ts(-19 * 86400))
        assert _h(db)["items_stalled_seconds"] is None

    def test_eligibility_time_is_next_retry_at_when_set(self, db, factory, user, quiet_integration):
        _item(factory, quiet_integration, user, acquisition_status="retry", attempts=1,
              created_at=ts(-19 * 86400), next_retry_at=ts(-100))
        assert 99 <= _h(db)["items_stalled_seconds"] <= 102

    def test_an_expired_processing_lease_counts_as_stalled(self, db, factory, user, quiet_integration):
        _item(factory, quiet_integration, user, acquisition_status="processing", attempts=1,
              lease_owner="dead", lease_expires_at=ts(-60), created_at=ts(-7200))
        result = _h(db, warning_seconds=3600)
        assert result["items_stalled_seconds"] >= 7199
        assert result["status"] == "degraded"


def test_seconds_round_half_away_from_zero():
    assert health._seconds_since("2026-01-01T00:00:10.500000Z", "2026-01-01T00:00:00.000000Z") == 11
    assert health._seconds_since("2026-01-01T00:00:10.499999Z", "2026-01-01T00:00:00.000000Z") == 10
    assert health._seconds_since("2026-01-01T00:00:00.000000Z", "2026-01-01T00:00:10.000000Z") == 0
    assert health._seconds_since("2026-01-01T00:00:00.000000Z", None) is None


def test_ping(db):
    assert health.ping(db) == "sqlite"
