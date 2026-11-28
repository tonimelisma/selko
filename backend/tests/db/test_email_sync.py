"""`selko.db.email_sync` against a real SQLite file.

Ports the database assertions of
integration/test_integration_email_ingestion_v2.py, the sync half of
test_integration_email_state_machine.py, test_integration_graph_ledger.py,
test_integration_ingestion_stall_signal.py's claim predicate and the lease
drill, plus the tests the plan adds (02-data-layer.md §2.2, §2.11).
"""

from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any

import pytest
from selko.db import codec, errors
from selko.db import email_sync as es


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def signal(self, work_type: str) -> None:
        self.calls.append(work_type)

    def publish(self, topic: str, message: Any) -> int:
        self.calls.append((topic, message["resource"], message["operation"]))
        return 0


def _ts(seconds: float = 0) -> str:
    return codec.to_timestamp(codec.utc_now() + timedelta(seconds=seconds))  # type: ignore[return-value]


def _set(db, table: str, key: str, key_value: str, **fields: Any) -> None:
    values = db.schema.encode(table, fields)
    with db.write() as tx:
        tx.execute(
            f"UPDATE {table} SET {', '.join(f'{c} = ?' for c in values)} WHERE {key} = ?",
            (*values.values(), key_value),
        )


def _state(db, integration_id: str) -> dict[str, Any]:
    state = es.get_sync_state(db, integration_id)
    assert state is not None
    return state


def _run(db, run_id: str) -> dict[str, Any]:
    return db.schema.decode("email_sync_runs", db.query_one("SELECT * FROM email_sync_runs WHERE id = ?", (run_id,)))


@pytest.fixture
def user(factory) -> str:
    return factory.user()


@pytest.fixture
def synced(db, factory, user) -> str:
    """An active Gmail integration due for a poll; its state came from the trigger."""
    integration_id = factory.integration(user)
    assert es.get_sync_state(db, integration_id) is not None, "trigger must provision sync state"
    _set(db, "email_sync_state", "integration_id", integration_id, next_poll_at=_ts(-60))
    return integration_id


# --- the ensure_email_sync_state trigger (18) -------------------------------


# Validates: SEL-001
def test_newly_connected_integration_becomes_pollable(db, factory, user):
    integration_id = factory.integration(user)
    state = _state(db, integration_id)
    assert state["provider"] == "gmail"
    assert state["next_poll_at"] <= _ts()
    assert state["initial_watermark_at"] <= _ts(-14 * 86400 + 5)
    _set(db, "email_sync_state", "integration_id", integration_id, next_poll_at="2000-01-01T00:00:00.000000Z")
    claim = es.claim_due_email_sync(db, "worker-a", 900)
    assert claim is not None and claim["integration_id"] == integration_id


# Validates: SEL-002
def test_non_email_providers_get_no_sync_state(db, factory, user):
    integration_id = factory.integration(user, provider="google_calendar")
    assert es.get_sync_state(db, integration_id) is None


# Validates: SEL-001
def test_reconnecting_clears_backoff_but_respects_a_live_lease(db, synced):
    _set(db, "email_sync_state", "integration_id", synced, consecutive_failures=5, next_poll_at=_ts(1800))
    _set(db, "integrations", "id", synced, status="expired")
    _set(db, "integrations", "id", synced, status="active")
    state = _state(db, synced)
    assert state["consecutive_failures"] == 0
    assert state["next_poll_at"] <= _ts()

    _set(db, "email_sync_state", "integration_id", synced,
         lease_owner="worker-x", lease_expires_at=_ts(600), next_poll_at=_ts(600))
    _set(db, "integrations", "id", synced, status="active")
    assert _state(db, synced)["next_poll_at"] > _ts()


# --- claims (8, 9) -----------------------------------------------------------


# Validates: SEL-006
def test_only_one_worker_owns_an_integration_and_expired_leases_return(db, synced):
    owned = es.claim_due_email_sync(db, "worker-a", 900)
    assert owned is not None and owned["integration_id"] == synced
    assert owned["run_kind"] == "initial"
    assert es.claim_due_email_sync(db, "worker-b", 900) is None

    _set(db, "email_sync_state", "integration_id", synced, lease_expires_at=_ts(-1))
    reclaimed = es.claim_due_email_sync(db, "worker-b", 900)
    assert reclaimed is not None and reclaimed["integration_id"] == synced


# Validates: SEL-004
def test_claim_returns_the_stored_lease_and_a_running_run(db, synced, user):
    claim = es.claim_due_email_sync(db, "worker-a", 900)
    assert set(claim) == {"integration_id", "user_id", "provider", "run_id", "run_kind",
                          "lease_generation", "lease_expires_at"}
    state = _state(db, synced)
    assert state["lease_expires_at"] == claim["lease_expires_at"]
    assert state["lease_owner"] == "worker-a"
    assert state["lease_generation"] == claim["lease_generation"] == 1
    assert state["last_started_at"] is not None
    run = _run(db, claim["run_id"])
    assert run["status"] == "running" and run["lease_generation"] == 1
    assert run["user_id"] == user and run["provider"] == "gmail"


# Validates: SEL-003
def test_claim_skips_inactive_and_not_yet_due(db, factory, user):
    expired = factory.integration(user, status="active")
    _set(db, "integrations", "id", expired, status="expired")
    _set(db, "email_sync_state", "integration_id", expired, next_poll_at=_ts(-60))
    other_user = factory.user()
    future = factory.integration(other_user)
    _set(db, "email_sync_state", "integration_id", future, next_poll_at=_ts(600))
    assert es.claim_due_email_sync(db, "w", 900) is None


# Validates: SEL-003
def test_claim_orders_by_next_poll_then_never_succeeded_first(db, factory):
    a, b, c = (factory.integration(factory.user()) for _ in range(3))
    same = _ts(-100)
    _set(db, "email_sync_state", "integration_id", a, next_poll_at=same, last_success_at=_ts(-500))
    _set(db, "email_sync_state", "integration_id", b, next_poll_at=same)  # never succeeded: NULLS FIRST
    _set(db, "email_sync_state", "integration_id", c, next_poll_at=_ts(-200), last_success_at=_ts(-50))
    order = [es.claim_due_email_sync(db, "w", 900)["integration_id"] for _ in range(3)]
    assert order == [c, b, a]
    assert es.claim_due_email_sync(db, "w", 900) is None


# Validates: SEL-004
def test_incremental_kind_after_a_success(db, synced):
    first = es.claim_due_email_sync(db, "w", 900)
    assert es.complete_email_sync(db, synced, first["run_id"], "w", first["lease_generation"], 300)
    _set(db, "email_sync_state", "integration_id", synced, next_poll_at=_ts(-1))
    assert es.claim_due_email_sync(db, "w", 900)["run_kind"] == "incremental"


# Validates: SEL-004
def test_lease_seconds_floor_is_one(db, synced):
    claim = es.claim_due_email_sync(db, "w", 0)
    assert claim["lease_expires_at"] > _ts()


# Validates: SEL-005
def test_next_sync_claim_abandons_previous_expired_run(db, synced):
    _set(db, "email_sync_state", "integration_id", synced,
         next_poll_at=_ts(-60), lease_owner="dead-worker", lease_expires_at=_ts(-1))
    first = es.claim_due_email_sync(db, "new-worker-a", 300)
    _set(db, "email_sync_state", "integration_id", synced, next_poll_at=_ts(-60), lease_expires_at=_ts(-1))
    second = es.claim_due_email_sync(db, "new-worker-b", 300)
    assert second["lease_generation"] > first["lease_generation"]
    assert _run(db, first["run_id"])["status"] == "abandoned"
    assert _run(db, first["run_id"])["completed_at"] is not None
    assert _run(db, second["run_id"])["status"] == "running"


# Validates: SEL-005
def test_one_running_run_per_integration_is_a_database_invariant(db, synced, user):
    def insert():
        with db.write() as tx:
            tx.execute(
                "INSERT INTO email_sync_runs (id, integration_id, user_id, provider, run_kind, status)"
                " VALUES (?, ?, ?, 'gmail', 'manual_repair', 'running')",
                (codec.new_id(), synced, user),
            )

    insert()
    with pytest.raises(errors.UniqueViolation):
        insert()


# Validates: SEL-011
def test_reconciliation_claim_kinds(db, synced):
    # Due for a normal poll: not a reconciliation candidate (next_poll_at must be in the future).
    assert es.claim_due_email_reconciliation(db, "w", 900) is None
    _set(db, "email_sync_state", "integration_id", synced, next_poll_at=_ts(600))
    claim = es.claim_due_email_reconciliation(db, "w", 900)
    assert claim["run_kind"] == "daily_reconcile"  # never reconciled
    assert es.claim_due_email_reconciliation(db, "w2", 900) is None  # lease held
    assert es.complete_email_sync(db, synced, claim["run_id"], "w", claim["lease_generation"], 600, reconciled=True)
    assert _state(db, synced)["last_reconciled_at"] is not None
    assert es.claim_due_email_reconciliation(db, "w", 900) is None  # reconciled just now

    _set(db, "email_sync_state", "integration_id", synced, last_reconciled_at=_ts(-2 * 86400))
    assert es.claim_due_email_reconciliation(db, "w", 900)["run_kind"] == "daily_reconcile"
    _set(db, "email_sync_state", "integration_id", synced,
         last_reconciled_at=_ts(-8 * 86400), lease_owner=None, lease_expires_at=None)
    assert es.claim_due_email_reconciliation(db, "w", 900)["run_kind"] == "weekly_reconcile"


# Validates: SEL-011
def test_reconciliation_orders_never_reconciled_first(db, factory):
    a, b = factory.integration(factory.user()), factory.integration(factory.user())
    _set(db, "email_sync_state", "integration_id", a, next_poll_at=_ts(100), last_reconciled_at=_ts(-3 * 86400))
    _set(db, "email_sync_state", "integration_id", b, next_poll_at=_ts(900))
    assert es.claim_due_email_reconciliation(db, "w", 900)["integration_id"] == b
    assert es.claim_due_email_reconciliation(db, "w", 900)["integration_id"] == a


# Validates: SEL-006
def test_concurrent_claims_never_share_an_integration(db, factory):
    ids = [factory.integration(factory.user()) for _ in range(6)]
    for integration_id in ids:
        _set(db, "email_sync_state", "integration_id", integration_id, next_poll_at=_ts(-60))
    results: list[Any] = []
    lock = threading.Lock()

    def worker(n: int) -> None:
        while True:
            claim = es.claim_due_email_sync(db, f"w{n}", 900)
            if claim is None:
                return
            with lock:
                results.append(claim["integration_id"])

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == sorted(ids)


# --- heartbeat / complete / fail (10-12) ------------------------------------


# Validates: SEL-007, SEL-008
def test_heartbeat_and_completion_require_matching_ownership(db, synced):
    claim = es.claim_due_email_sync(db, "worker-a", 900)
    gen = claim["lease_generation"]
    assert es.heartbeat_email_sync(db, synced, "worker-a", gen, 900) is True
    assert es.heartbeat_email_sync(db, synced, "worker-b", gen, 900) is False
    assert es.heartbeat_email_sync(db, synced, "worker-a", gen + 1, 900) is False
    assert es.complete_email_sync(db, synced, claim["run_id"], "worker-b", gen, 300, False) is False
    assert es.complete_email_sync(db, synced, claim["run_id"], "worker-a", gen, 300, False) is True

    state = _state(db, synced)
    assert state["lease_owner"] is None and state["lease_expires_at"] is None
    assert state["last_success_at"] == state["last_discovery_at"]
    assert state["next_poll_at"] > _ts(290)
    assert _run(db, claim["run_id"])["status"] == "completed"


# Validates: SEL-007
def test_heartbeat_refuses_an_expired_lease(db, synced):
    claim = es.claim_due_email_sync(db, "w", 900)
    _set(db, "email_sync_state", "integration_id", synced, lease_expires_at=_ts(-1))
    assert es.heartbeat_email_sync(db, synced, "w", claim["lease_generation"], 900) is False
    assert es.complete_email_sync(db, synced, claim["run_id"], "w", claim["lease_generation"]) is False


# Validates: SEL-007
def test_stale_sync_generation_cannot_complete_new_run(db, synced):
    first = es.claim_due_email_sync(db, "worker-a", 1)
    _set(db, "email_sync_state", "integration_id", synced, lease_expires_at=_ts(-1), next_poll_at=_ts(-60))
    second = es.claim_due_email_sync(db, "worker-b", 300)
    assert es.complete_email_sync(db, synced, first["run_id"], "worker-a", first["lease_generation"], 60) is False
    assert second["lease_generation"] > first["lease_generation"]
    # Even the same worker id cannot complete with the old generation.
    _set(db, "email_sync_state", "integration_id", synced, lease_owner="worker-a")
    assert es.complete_email_sync(db, synced, second["run_id"], "worker-a", first["lease_generation"]) is False
    assert es.fail_email_sync(db, synced, first["run_id"], "worker-a", first["lease_generation"], "x") is False
    assert _run(db, second["run_id"])["status"] == "running"


# Validates: SEL-009
def test_failure_backoff_grows_and_stays_capped(db, synced):
    delays = []
    for _ in range(4):
        _set(db, "email_sync_state", "integration_id", synced,
             next_poll_at=_ts(-60), lease_owner=None, lease_expires_at=None)
        claim = es.claim_due_email_sync(db, "worker-a", 900)
        assert es.fail_email_sync(db, synced, claim["run_id"], "worker-a", claim["lease_generation"],
                                  "provider_transient", "transient", 60, 300, False)
        state = _state(db, synced)
        delays.append((codec.parse_timestamp(state["next_poll_at"]) - codec.utc_now()).total_seconds())
    assert _state(db, synced)["consecutive_failures"] == 4
    assert delays[1] > delays[0]
    assert all(delay <= 300 for delay in delays)
    assert [round(d / 60) for d in delays] == [1, 2, 4, 5]


# Validates: SEL-009
def test_fail_records_truncated_codes_and_releases_the_lease(db, synced):
    claim = es.claim_due_email_sync(db, "w", 900)
    assert es.fail_email_sync(db, synced, claim["run_id"], "w", claim["lease_generation"],
                              "c" * 150, "d" * 600)
    run = _run(db, claim["run_id"])
    assert run["status"] == "failed"
    assert run["error_code"] == "c" * 100 and run["error_detail"] == "d" * 500
    state = _state(db, synced)
    assert state["lease_owner"] is None and state["last_error_code"] == "c" * 100


# Validates: SEL-010
def test_auth_failure_expires_the_integration_and_sends_a_live_hint(db, synced, user):
    claim = es.claim_due_email_sync(db, "w", 900)
    recorder = _Recorder()
    db.bus = recorder
    assert es.fail_email_sync(db, synced, claim["run_id"], "w", claim["lease_generation"],
                              "provider_auth", None, 60, 1800, True)
    row = db.query_one("SELECT status FROM integrations WHERE id = ?", (synced,))
    assert row["status"] == "expired"
    assert (f"user:{user}", "integrations", "UPDATE") in recorder.calls
    # An expired integration is not claimable even when due.
    _set(db, "email_sync_state", "integration_id", synced, next_poll_at=_ts(-60))
    assert es.claim_due_email_sync(db, "w", 900) is None


# Validates: SEL-010
def test_non_auth_failure_leaves_the_integration_active(db, synced):
    claim = es.claim_due_email_sync(db, "w", 900)
    es.fail_email_sync(db, synced, claim["run_id"], "w", claim["lease_generation"], "transient")
    assert db.query_one("SELECT status FROM integrations WHERE id = ?", (synced,))["status"] == "active"


# --- discovery pages (13) ----------------------------------------------------


def _items(db, integration_id):
    rows = db.query("SELECT * FROM email_ingestion_items WHERE integration_id = ? ORDER BY provider_message_id",
                    (integration_id,))
    return [db.schema.decode("email_ingestion_items", r) for r in rows]


# Validates: SEL-034
def test_discovery_page_write_records_run_counters(db, synced):
    claim = es.claim_due_email_sync(db, "worker-a", 900)
    result = es.upsert_discovered_email_items(
        db, synced, claim["run_id"], [{"provider_message_id": "m1", "provider_folder_ids": ["INBOX"]}]
    )
    assert result == {"inserted_count": 1, "existing_count": 0, "provider_ids_seen": 1}
    run = _run(db, claim["run_id"])
    assert run["provider_ids_seen"] == 1 and run["ingestion_items_inserted"] == 1
    assert run["ingestion_items_existing"] == 0

    again = es.upsert_discovered_email_items(
        db, synced, claim["run_id"],
        [{"provider_message_id": "m1"}, {"provider_message_id": "m2"}, {"provider_message_id": ""}],
    )
    assert again == {"inserted_count": 2, "existing_count": 1, "provider_ids_seen": 3}
    run = _run(db, claim["run_id"])
    assert (run["provider_ids_seen"], run["ingestion_items_inserted"], run["ingestion_items_existing"]) == (4, 3, 1)
    assert [i["provider_message_id"] for i in _items(db, synced)] == ["m1", "m2"]


# Validates: SEL-032
def test_new_items_are_pending_with_the_transaction_time(db, synced, user):
    claim = es.claim_due_email_sync(db, "w", 900)
    es.upsert_discovered_email_items(db, synced, claim["run_id"], [
        {"provider_message_id": "m1", "provider_folder_ids": ["A", "A"], "change_kind": "membership_change"},
    ])
    (item,) = _items(db, synced)
    assert item["acquisition_status"] == "pending"
    assert item["provider_folder_ids"] == ["A", "A"]  # insert keeps the array as given, like Postgres
    assert item["change_kind"] == "membership_change"
    assert item["user_id"] == user and item["provider"] == "gmail"
    assert item["created_at"] == item["first_discovered_at"] == item["last_discovered_at"]
    assert len(item["created_at"]) == 27


# Validates: SEL-032
def test_identity_upsert_unions_folders_and_protects_completed_items(db, synced):
    claim = es.claim_due_email_sync(db, "worker-a", 900)
    run = claim["run_id"]
    es.upsert_discovered_email_items(db, synced, run, [{"provider_message_id": "m1", "provider_folder_ids": ["INBOX"]}])
    es.upsert_discovered_email_items(db, synced, run, [{"provider_message_id": "m1", "provider_folder_ids": ["ARCHIVE"]}])
    (item,) = _items(db, synced)
    assert sorted(item["provider_folder_ids"]) == ["ARCHIVE", "INBOX"]

    _set(db, "email_ingestion_items", "id", item["id"], acquisition_status="completed", change_kind="upsert")
    es.upsert_discovered_email_items(db, synced, run, [
        {"provider_message_id": "m1", "provider_folder_ids": ["INBOX"], "change_kind": "membership_change"},
    ])
    (after,) = _items(db, synced)
    assert after["acquisition_status"] == "completed"
    assert after["change_kind"] == "upsert"
    assert sorted(after["provider_folder_ids"]) == ["ARCHIVE", "INBOX"]


# Validates: SEL-032
def test_rediscovery_requeues_retry_but_not_processing_or_dead_letter(db, synced):
    claim = es.claim_due_email_sync(db, "w", 900)
    es.upsert_discovered_email_items(db, synced, claim["run_id"], [
        {"provider_message_id": m} for m in ("retry", "proc", "dead")
    ])
    by_mid = {i["provider_message_id"]: i["id"] for i in _items(db, synced)}
    _set(db, "email_ingestion_items", "id", by_mid["retry"], acquisition_status="retry", next_retry_at=_ts(600))
    _set(db, "email_ingestion_items", "id", by_mid["proc"], acquisition_status="processing")
    _set(db, "email_ingestion_items", "id", by_mid["dead"], acquisition_status="dead_letter")
    es.upsert_discovered_email_items(db, synced, claim["run_id"], [
        {"provider_message_id": m, "change_kind": "membership_change"} for m in ("retry", "proc", "dead")
    ])
    status = {i["provider_message_id"]: (i["acquisition_status"], i["change_kind"]) for i in _items(db, synced)}
    assert status == {
        "retry": ("pending", "membership_change"),
        "proc": ("processing", "membership_change"),
        "dead": ("dead_letter", "membership_change"),
    }


# Validates: SEL-034
def test_discovery_emits_one_item_pending_signal_per_commit(db, synced):
    claim = es.claim_due_email_sync(db, "w", 900)
    recorder = _Recorder()
    db.signals = recorder
    es.upsert_discovered_email_items(db, synced, claim["run_id"], [
        {"provider_message_id": f"m{n}"} for n in range(5)
    ])
    assert recorder.calls == ["item_pending"]


# Validates: SEL-034
def test_cursor_advances_only_when_discovery_supplies_one(db, synced):
    _set(db, "integrations", "id", synced, sync_cursor="history-999")
    claim = es.claim_due_email_sync(db, "worker-a", 900)
    es.upsert_discovered_email_items(db, synced, claim["run_id"],
                                     [{"provider_message_id": "m2", "provider_folder_ids": ["INBOX"]}])
    row = db.query_one("SELECT sync_cursor, last_sync_at FROM integrations WHERE id = ?", (synced,))
    assert row["sync_cursor"] == "history-999" and row["last_sync_at"] is None
    es.upsert_discovered_email_items(db, synced, claim["run_id"], [], cursor="history-1000")
    row = db.query_one("SELECT sync_cursor, last_sync_at FROM integrations WHERE id = ?", (synced,))
    assert row["sync_cursor"] == "history-1000" and row["last_sync_at"] is not None


# Validates: SEL-027
def test_folder_cursor_goes_to_the_folder_of_this_integration_only(db, factory, synced, user):
    (folder,) = es.upsert_folders(db, synced, [_folder_row(user, synced, "inbox-id")])
    other = factory.integration(factory.user(), provider="outlook")
    claim = es.claim_due_email_sync(db, "w", 900)
    es.upsert_discovered_email_items(db, synced, claim["run_id"], [], cursor="delta-1", folder_id=folder["id"])
    assert es.folders_for_integration(db, synced)[0]["sync_cursor"] == "delta-1"
    assert db.query_one("SELECT sync_cursor FROM integrations WHERE id = ?", (synced,))["sync_cursor"] is None
    # A folder id from another integration is not touched.
    es.upsert_discovered_email_items(db, other, claim["run_id"], [], cursor="delta-2", folder_id=folder["id"])
    assert es.folders_for_integration(db, synced)[0]["sync_cursor"] == "delta-1"


# Validates: SEL-034
def test_counters_only_move_on_a_running_run(db, synced):
    claim = es.claim_due_email_sync(db, "w", 900)
    es.complete_email_sync(db, synced, claim["run_id"], "w", claim["lease_generation"])
    es.upsert_discovered_email_items(db, synced, claim["run_id"], [{"provider_message_id": "late"}])
    assert _run(db, claim["run_id"])["provider_ids_seen"] == 0
    assert [i["provider_message_id"] for i in _items(db, synced)] == ["late"]


def test_unknown_integration_raises_not_found(db):
    with pytest.raises(errors.NotFound, match="Unknown email integration"):
        es.upsert_discovered_email_items(db, codec.new_id(), codec.new_id(), [])


# Validates: SEL-033
def test_duplicate_identity_in_one_page_fails_the_page_as_postgres_did(db, synced):
    claim = es.claim_due_email_sync(db, "w", 900)
    with pytest.raises(errors.DbError):
        es.upsert_discovered_email_items(db, synced, claim["run_id"],
                                         [{"provider_message_id": "m"}, {"provider_message_id": "m"}])
    assert _items(db, synced) == []


def test_known_provider_message_ids_is_scoped_and_chunked(db, factory, synced):
    claim = es.claim_due_email_sync(db, "w", 900)
    es.upsert_discovered_email_items(db, synced, claim["run_id"], [{"provider_message_id": f"m{n}"} for n in range(5)])
    other = factory.integration(factory.user())
    assert es.known_provider_message_ids(db, synced, ["m0", "m3", "zz", "", None], chunk=2) == {"m0", "m3"}
    assert es.known_provider_message_ids(db, other, ["m0"]) == set()


# --- ingestion items (14-16) ------------------------------------------------


def _item(db, integration_id, user_id, **fields) -> str:
    item_id = codec.new_id()
    values = {"id": item_id, "integration_id": integration_id, "user_id": user_id, "provider": "gmail",
              "provider_message_id": f"msg-{item_id}", "created_at": _ts(), **fields}
    values = db.schema.encode("email_ingestion_items", values)
    with db.write() as tx:
        tx.execute(
            f"INSERT INTO email_ingestion_items ({', '.join(values)}) VALUES ({', '.join('?' for _ in values)})",
            tuple(values.values()),
        )
    return item_id


# Validates: SEL-050
def test_claim_item_oldest_first_and_leases_it(db, synced, user):
    newer = _item(db, synced, user, created_at=_ts(-10))
    older = _item(db, synced, user, created_at=_ts(-100))
    item = es.claim_email_ingestion_item(db, "w", 900)
    assert item["id"] == older
    assert item["acquisition_status"] == "processing"
    assert item["attempts"] == 1 and item["lease_owner"] == "w"
    assert item["lease_expires_at"] > _ts(890)
    assert isinstance(item["provider_folder_ids"], list)
    assert es.claim_email_ingestion_item(db, "w", 900)["id"] == newer
    assert es.claim_email_ingestion_item(db, "w", 900) is None


# Validates: SEL-050
def test_a_row_serving_its_retry_backoff_is_not_claimable(db, synced, user):
    waiting = _item(db, synced, user, acquisition_status="retry", attempts=1,
                    created_at=_ts(-19 * 86400), next_retry_at=_ts(600))
    assert es.claim_email_ingestion_item(db, "w") is None
    _set(db, "email_ingestion_items", "id", waiting, next_retry_at=_ts(-1))
    assert es.claim_email_ingestion_item(db, "w")["id"] == waiting


# Validates: SEL-050
def test_claim_item_respects_attempts_live_leases_and_terminal_states(db, synced, user):
    _item(db, synced, user, attempts=8, max_attempts=8)
    _item(db, synced, user, acquisition_status="processing", attempts=1, lease_owner="o", lease_expires_at=_ts(900))
    for status in ("completed", "dead_letter", "removed"):
        _item(db, synced, user, acquisition_status=status)
    assert es.claim_email_ingestion_item(db, "w") is None
    expired = _item(db, synced, user, acquisition_status="processing", attempts=1,
                    lease_owner="dead", lease_expires_at=_ts(-1))
    reclaimed = es.claim_email_ingestion_item(db, "w")
    assert reclaimed["id"] == expired and reclaimed["attempts"] == 2 and reclaimed["lease_owner"] == "w"


# Validates: SEL-050
def test_concurrent_item_claims_never_share_a_row(db, synced, user):
    ids = {_item(db, synced, user) for _ in range(20)}
    claimed: list[str] = []
    lock = threading.Lock()

    def worker(n: int) -> None:
        while (item := es.claim_email_ingestion_item(db, f"w{n}")) is not None:
            with lock:
                claimed.append(item["id"])

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(claimed) == len(ids) and set(claimed) == ids


# Validates: SEL-053
def test_complete_item_is_fenced_on_owner_and_status(db, factory, synced, user):
    item_id = _item(db, synced, user)
    email_id = factory.email(user)
    assert es.complete_email_ingestion_item(db, item_id, "w", email_id) is False  # not processing
    es.claim_email_ingestion_item(db, "w")
    assert es.complete_email_ingestion_item(db, item_id, "other", email_id) is False
    assert es.complete_email_ingestion_item(db, item_id, "w", email_id) is True
    row = factory.row("email_ingestion_items", item_id)
    assert row["acquisition_status"] == "completed" and row["email_id"] == email_id
    assert row["lease_owner"] is None and row["completed_at"] is not None
    assert es.complete_email_ingestion_item(db, item_id, "w", email_id) is False


# Validates: SEL-055
def test_no_acquisition_failure_is_terminal_on_first_attempt(db, factory, synced, user):
    item_id = _item(db, synced, user)
    es.claim_email_ingestion_item(db, "w")
    assert es.fail_email_ingestion_item(db, item_id, "w", "provider_auth", 60, 1800, False) is True
    row = factory.row("email_ingestion_items", item_id)
    assert row["acquisition_status"] == "retry"
    assert row["lease_owner"] is None and row["last_error_code"] == "provider_auth"
    delay = (codec.parse_timestamp(row["next_retry_at"]) - codec.utc_now()).total_seconds()
    assert 55 <= delay <= 60  # attempt 1: base * 2**0
    assert es.fail_email_ingestion_item(db, item_id, "w", "x") is False  # lease released


def test_permanent_error_is_terminal_on_first_attempt(db, factory, synced, user):
    item_id = _item(db, synced, user)
    es.claim_email_ingestion_item(db, "w")
    assert es.fail_email_ingestion_item(db, item_id, "w", "e" * 120, terminal=True) is True
    row = factory.row("email_ingestion_items", item_id)
    assert row["acquisition_status"] == "dead_letter" and row["next_retry_at"] is None
    assert row["last_error_code"] == "e" * 100


# Validates: SEL-055
def test_exhausted_attempts_dead_letter_and_backoff_is_capped(db, factory, synced, user):
    item_id = _item(db, synced, user, attempts=6, max_attempts=8, lease_owner="w")
    assert es.fail_email_ingestion_item(db, item_id, "w", "x", 60, 1800)
    row = factory.row("email_ingestion_items", item_id)
    delay = (codec.parse_timestamp(row["next_retry_at"]) - codec.utc_now()).total_seconds()
    assert 1790 <= delay <= 1800  # min(1800, 60 * 2**5)
    _set(db, "email_ingestion_items", "id", item_id, attempts=8, lease_owner="w")
    es.fail_email_ingestion_item(db, item_id, "w", "x")
    assert factory.row("email_ingestion_items", item_id)["acquisition_status"] == "dead_letter"


def test_zero_attempts_backoff_rounds_half_to_even_like_postgres(db, factory, synced, user):
    # power(2, -1)::integer is 0 in Postgres (rint), so the retry is immediate.
    item_id = _item(db, synced, user, attempts=0, lease_owner="w")
    before = _ts()
    es.fail_email_ingestion_item(db, item_id, "w", "x", 60, 1800)
    row = factory.row("email_ingestion_items", item_id)
    assert row["acquisition_status"] == "retry" and before <= row["next_retry_at"] <= _ts()


# Validates: SEL-053
def test_remove_item_is_fenced_on_owner(db, factory, synced, user):
    item_id = _item(db, synced, user)
    es.claim_email_ingestion_item(db, "w")
    assert es.remove_ingestion_item(db, item_id, "other") is False
    assert es.remove_ingestion_item(db, item_id, "w") is True
    row = factory.row("email_ingestion_items", item_id)
    assert row["acquisition_status"] == "removed" and row["completed_at"] is not None
    assert row["lease_owner"] is None


def test_dead_letter_integration_ids(db, factory, synced, user):
    _item(db, synced, user, acquisition_status="dead_letter")
    other = factory.integration(factory.user())
    _item(db, other, db.query_one("SELECT user_id FROM integrations WHERE id = ?", (other,))["user_id"])
    assert es.dead_letter_item_integration_ids(db) == {synced}

    email_id = factory.email(user, integration_id=synced)
    with db.write() as tx:
        tx.execute(
            "INSERT INTO attachments (id, email_id, user_id, filename, ingestion_status)"
            " VALUES (?, ?, ?, 'a.pdf', 'dead_letter')",
            (codec.new_id(), email_id, user),
        )
    assert es.dead_letter_attachment_integration_ids(db) == {synced}


# --- request_email_sync_now (17) -------------------------------------------


# Validates: SEL-012
def test_request_sync_now_respects_lease_and_owner(db, factory, synced, user):
    _set(db, "email_sync_state", "integration_id", synced, next_poll_at=_ts(600))
    stranger = factory.user()
    assert es.request_email_sync_now(db, stranger, synced) is False
    assert es.request_email_sync_now(db, None, synced) is False
    assert _state(db, synced)["next_poll_at"] > _ts()

    assert es.request_email_sync_now(db, user, synced) is True
    assert _state(db, synced)["next_poll_at"] <= _ts()

    _set(db, "email_sync_state", "integration_id", synced,
         lease_owner="w", lease_expires_at=_ts(600), next_poll_at=_ts(600))
    assert es.request_email_sync_now(db, user, synced) is False
    assert _state(db, synced)["next_poll_at"] > _ts()

    calendar = factory.integration(user, provider="google_calendar")
    assert es.request_email_sync_now(db, user, calendar) is False  # owned, but no sync state


# --- sync state reads/writes ------------------------------------------------


def test_folders_refreshed_at_round_trip_and_all_states(db, synced, factory):
    assert es.folders_refreshed_at(db, synced) is None
    assert es.mark_folders_refreshed(db, synced) is True
    stamp = es.folders_refreshed_at(db, synced)
    assert stamp is not None and len(stamp) == 27
    assert es.folders_refreshed_at(db, codec.new_id()) is None
    assert es.mark_folders_refreshed(db, codec.new_id()) is False
    second = factory.integration(factory.user(), provider="outlook")
    assert {s["integration_id"] for s in es.all_states(db)} == {synced, second}


# --- folders (59, §3.5) ------------------------------------------------------


def _folder_row(user_id, integration_id, provider_folder_id, **extra) -> dict[str, Any]:
    row = {
        "user_id": user_id, "integration_id": integration_id, "provider": "gmail",
        "provider_folder_id": provider_folder_id, "parent_folder_id": None,
        "name": provider_folder_id, "full_path": provider_folder_id, "folder_kind": "label",
        "is_system": False, "is_scannable": True, "is_permanently_excluded": False, "system_kind": None,
        "classification_decision": "include", "classification_reason": "r", "user_override": False,
        "is_included": True, "updated_at": codec.utc_now().isoformat(),
    }
    row.update(extra)
    return row


# Validates: SEL-041
def test_upsert_folders_inserts_then_updates_in_place(db, synced, user):
    first = es.upsert_folders(db, synced, [_folder_row(user, synced, "L1"), _folder_row(user, synced, "L2")])
    assert [f["provider_folder_id"] for f in first] == ["L1", "L2"]
    assert first[0]["is_included"] is True and first[0]["discovered_at"]
    assert len(first[0]["updated_at"]) == 27  # an ISO string from the service is stored as codec text

    with db.write() as tx:
        tx.execute("UPDATE email_folders SET sync_cursor = 'c1' WHERE id = ?", (first[0]["id"],))
    second = es.upsert_folders(db, synced, [
        _folder_row(user, synced, "L1", name="Renamed", sync_cursor="c1"),
        _folder_row(user, synced, "L2", is_included=False),
    ])
    assert [f["id"] for f in second] == [f["id"] for f in first]
    assert second[0]["name"] == "Renamed" and second[0]["sync_cursor"] == "c1"
    assert second[0]["discovered_at"] == first[0]["discovered_at"]
    # Mixed batch: the row without sync_cursor binds NULL (supabase-py default_to_null).
    assert second[1]["sync_cursor"] is None and second[1]["is_included"] is False
    assert es.upsert_folders(db, synced, []) == []
    with pytest.raises(errors.DbError):
        es.upsert_folders(db, synced, [_folder_row(user, synced, "X"), _folder_row(user, synced, "X")])


def test_folder_reads_and_delete(db, factory, synced, user):
    es.upsert_folders(db, synced, [
        _folder_row(user, synced, "b-label", full_path="b"),
        _folder_row(user, synced, "a-label", full_path="a", is_included=False),
        _folder_row(user, synced, "INBOX", is_system=True),
    ])
    assert es.folder_ids(db, synced, "gmail", False) == ["a-label"]
    assert set(es.folder_ids(db, synced, "gmail", True)) == {"b-label", "INBOX"}
    assert es.folder_ids(db, synced, "outlook", True) == []
    assert len(es.folders_for_integration(db, synced)) == 3
    assert es.folders_for_integration(db, synced, "outlook") == []

    listed = es.list_user_folders(db, user, "gmail")
    assert [f["full_path"] for f in listed] == ["a", "b"]  # system folders hidden, ordered by path
    assert es.get_user_folder(db, user, listed[0]["id"], "gmail")["provider_folder_id"] == "a-label"
    assert es.get_user_folder(db, factory.user(), listed[0]["id"], "gmail") is None
    inbox = next(f for f in es.folders_for_integration(db, synced) if f["is_system"])
    assert es.get_user_folder(db, user, inbox["id"], "gmail") is None

    other = factory.integration(factory.user())
    assert es.delete_folder(db, other, listed[0]["id"]) is False
    assert es.delete_folder(db, synced, listed[0]["id"]) is True
    assert len(es.folders_for_integration(db, synced)) == 2


# Validates: SEL-044
def test_set_email_folder_preference(db, factory, synced, user):
    folders = es.upsert_folders(db, synced, [
        _folder_row(user, synced, "L", sync_cursor="cur"),
        _folder_row(user, synced, "INBOX", is_system=True),
        _folder_row(user, synced, "SPAM", is_permanently_excluded=True, is_included=False),
    ])
    label, inbox, spam = folders
    updated = es.set_email_folder_preference(db, user, label["id"], False)
    assert updated["is_included"] is False and updated["user_override"] is True
    assert updated["sync_cursor"] is None
    assert updated["updated_at"] > label["updated_at"]
    assert es.set_email_folder_preference(db, user, inbox["id"], False) is None
    assert es.set_email_folder_preference(db, user, spam["id"], True) is None
    assert es.set_email_folder_preference(db, factory.user(), label["id"], True) is None
    assert factory.row("email_folders", label["id"])["is_included"] is False
    with pytest.raises(errors.InvalidArgument, match="Authentication required"):
        es.set_email_folder_preference(db, None, label["id"], True)


def test_malformed_ids_are_invalid_arguments(db):
    with pytest.raises(errors.InvalidArgument):
        es.heartbeat_email_sync(db, "not-a-uuid", "w", 1, 900)


# --- integration reads for the ingestion workers (wire/email-ingestion) -------


def test_integration_reads_for_the_workers(db, factory, user):
    gmail = factory.integration(user, provider="gmail")
    calendar = factory.integration(user, provider="google_calendar")
    outlook = factory.integration(user, provider="outlook", status="expired")

    assert es.integration_statuses(db) == {gmail: "active", calendar: "active", outlook: "expired"}
    assert es.get_integration_by_id(db, gmail)["provider"] == "gmail"
    assert es.get_integration_by_id(db, codec.new_id()) is None
    # Mail-only Gmail is not a calendar; an expired Outlook is not polled.
    assert [r["id"] for r in es.active_calendar_integrations(db)] == [calendar]
