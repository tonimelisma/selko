"""selko.db.emails against a real SQLite file.

Ported from integration/test_integration_email_state_machine.py (email half),
test_integration_workers.py (email tests), test_integration_worker_pool_port.py,
test_integration_email_ingestion_v2.py, test_integration_calendar_components.py
and test_reliability.py's fail_email_processing outcomes.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from selko.db import codec, emails
from selko.db.errors import (
    CheckViolation,
    EmailActivelyLeased,
    InvalidArgument,
    NotFound,
    NotNullViolation,
)


def ts(delta_seconds: float = 0) -> str:
    return codec.to_timestamp(datetime.now(timezone.utc) + timedelta(seconds=delta_seconds))


def make_email(factory, user, **extra):
    values = {"email_provider": "gmail", "date_sent": "1900-01-01T00:00:00.000000Z",
              "provider_labels": ["INBOX"], "processing_status": "pending"}
    values.update(extra)
    return factory.email(user, **values)


def set_cols(db, table, row_id, **cols):
    with db.write() as tx:
        tx.execute(
            f"UPDATE {table} SET {', '.join(f'{c} = ?' for c in cols)} WHERE id = ?",
            (*cols.values(), row_id),
        )


class Recorder:
    def __init__(self):
        self.sent = []

    def signal(self, work_type):
        self.sent.append(work_type)


@pytest.fixture
def user(factory):
    return factory.user()


# --- claim_unprocessed_email -------------------------------------------------


def test_claim_takes_oldest_date_sent_nulls_last(db, factory, user):
    no_date = make_email(factory, user, date_sent=None)
    newer = make_email(factory, user, date_sent="2020-01-01T00:00:00.000000Z")
    older = make_email(factory, user, date_sent="2010-01-01T00:00:00.000000Z")
    order = [emails.claim_unprocessed_email(db, "w")["id"] for _ in range(3)]
    assert order == [older, newer, no_date]
    assert emails.claim_unprocessed_email(db, "w") is None


def test_claim_sets_lease_attempts_and_generation(db, factory, user):
    email_id = make_email(factory, user)
    claimed = emails.claim_unprocessed_email(db, "worker-a", 120)
    assert claimed["id"] == email_id
    assert claimed["processing_status"] == "processing"
    assert claimed["locked_by"] == "worker-a"
    assert claimed["attempts"] == 1
    assert claimed["lock_generation"] == 1
    assert claimed["processing_error"] is None
    until = codec.parse_timestamp(claimed["locked_until"])
    assert timedelta(seconds=110) < until - datetime.now(timezone.utc) <= timedelta(seconds=121)
    assert isinstance(claimed["is_unread"], bool)  # decoded


def test_claim_lease_is_at_least_one_second(db, factory, user):
    make_email(factory, user)
    claimed = emails.claim_unprocessed_email(db, "w", 0)
    assert codec.parse_timestamp(claimed["locked_until"]) > datetime.now(timezone.utc)


def test_claim_respects_next_retry_at_and_attempts(db, factory, user):
    make_email(factory, user, next_retry_at=ts(60))
    make_email(factory, user, processing_status="processed")
    assert emails.claim_unprocessed_email(db, "w") is None


def test_expired_processing_email_is_reclaimed_without_restart(db, factory, user):
    email_id = make_email(factory, user, processing_status="processing", attempts=1,
                          locked_by="dead-worker", locked_until=ts(-1))
    claimed = emails.claim_unprocessed_email(db, "new-worker")
    assert claimed["id"] == email_id
    assert claimed["processing_status"] == "processing"
    assert claimed["locked_by"] == "new-worker"
    assert claimed["lock_generation"] > 0
    assert claimed["attempts"] == 2


def test_one_expired_lease_is_reclaimed_per_call(db, factory, user):
    first = make_email(factory, user, processing_status="processing", attempts=1,
                       locked_by="dead", locked_until=ts(-20), next_retry_at=ts(600))
    second = make_email(factory, user, processing_status="processing", attempts=1,
                        locked_by="dead", locked_until=ts(-10), next_retry_at=ts(600))
    assert emails.claim_unprocessed_email(db, "w") is None
    assert factory.row("emails", first)["processing_status"] == "pending"
    assert factory.row("emails", second)["processing_status"] == "processing"


def test_expired_processing_email_at_attempt_limit_becomes_failed(db, factory, user):
    email_id = make_email(factory, user, processing_status="processing", attempts=3, max_attempts=3,
                          locked_by="dead-worker", locked_until=ts(-1))
    assert emails.claim_unprocessed_email(db, "new-worker") is None
    row = factory.row("emails", email_id)
    assert row["processing_status"] == "failed"
    assert row["dead_letter_reason"] == "lease_expired_at_limit"
    assert row["dead_letter_at"] is not None
    assert row["locked_by"] is None and row["locked_until"] is None


def test_live_lease_is_not_reclaimed(db, factory, user):
    email_id = make_email(factory, user, processing_status="processing", attempts=1,
                          locked_by="live", locked_until=ts(300))
    assert emails.claim_unprocessed_email(db, "w") is None
    assert factory.row("emails", email_id)["locked_by"] == "live"


def test_pending_email_cannot_equal_max_attempts(factory, user):
    with pytest.raises(CheckViolation):
        make_email(factory, user, attempts=3, max_attempts=3)


def test_reclaim_to_pending_emits_email_pending(db, factory, user):
    make_email(factory, user, processing_status="processing", attempts=1,
               locked_by="dead", locked_until=ts(-1), next_retry_at=ts(600))
    db.signals = Recorder()
    emails.claim_unprocessed_email(db, "w")
    assert db.signals.sent == ["email_pending"]


def test_two_threads_never_claim_the_same_email(db, factory, user):
    ids = {make_email(factory, user) for _ in range(40)}
    claimed: list[str] = []
    lock = threading.Lock()

    def worker(name):
        while True:
            row = emails.claim_unprocessed_email(db, name)
            if row is None:
                return
            with lock:
                claimed.append(row["id"])

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(claimed) == sorted(ids)
    assert len(set(claimed)) == len(claimed)


# --- the attachment readiness gate --------------------------------------------


def test_atomic_save_blocks_llm_claim_until_attachment_descriptors_settle(db, factory, user):
    integration = factory.integration(user)
    email_id = emails.save_email_with_attachment_descriptors(
        db, user,
        {"email_provider": "gmail", "provider_message_id": "race-msg", "subject": "race",
         "from_email": "sender@selko.local", "date_sent": "2000-01-01T00:00:00+00:00",
         "provider_labels": ["INBOX"], "has_attachments": True, "integration_id": integration},
        [{"provider_attachment_id": "att-1", "filename": "a.txt", "mime_type": "text/plain", "size_bytes": 10},
         {"provider_attachment_id": "att-2", "filename": "b.pdf", "mime_type": "application/pdf", "size_bytes": 200},
         {"provider_attachment_id": "att-3", "filename": "c.png", "mime_type": "image/png", "size_bytes": 1000}],
    )
    atts = db.query("SELECT provider_attachment_id, ingestion_status FROM attachments WHERE email_id = ?", (email_id,))
    assert {a["provider_attachment_id"] for a in atts} == {"att-1", "att-2", "att-3"}
    assert all(a["ingestion_status"] == "pending" for a in atts)
    assert not emails.email_is_claimable(db, email_id)
    assert emails.claim_unprocessed_email(db, "race-worker") is None

    with db.write() as tx:
        tx.execute("UPDATE attachments SET ingestion_status = 'retry' WHERE email_id = ? AND provider_attachment_id = 'att-1'", (email_id,))
        tx.execute("UPDATE attachments SET ingestion_status = 'stored' WHERE email_id = ? AND provider_attachment_id <> 'att-1'", (email_id,))
    assert emails.claim_unprocessed_email(db, "race-worker") is None  # retry still blocks

    with db.write() as tx:
        tx.execute("UPDATE attachments SET ingestion_status = 'dead_letter' WHERE email_id = ?", (email_id,))
    assert emails.email_is_claimable(db, email_id)
    assert emails.claim_unprocessed_email(db, "race-worker")["id"] == email_id


# --- fail_email_processing -----------------------------------------------------


def test_failure_transition_is_atomic(db, factory, user):
    email_id = make_email(factory, user, max_attempts=3)
    claimed = emails.claim_unprocessed_email(db, "worker-a")
    result = emails.fail_email_processing(db, email_id, "worker-a", claimed["lock_generation"],
                                          "provider-transient", "bounded detail", 1, 2)
    assert result["fenced"] is False
    assert result["status"] == "pending"
    assert result["attempts"] == 1
    current = factory.row("emails", email_id)
    assert current["processing_status"] == "pending"
    assert current["locked_by"] is None and current["locked_until"] is None
    assert current["next_retry_at"] == result["next_retry_at"]
    assert current["processing_error"] == "provider-transient"


def test_fail_email_processing_with_retry(db, factory, user):
    email_id = make_email(factory, user, max_attempts=3)
    claimed = emails.claim_unprocessed_email(db, "worker-1")
    emails.fail_email_processing(db, email_id, "worker-1", claimed["lock_generation"], "Test error", "Test error", 60, 1800)
    row = factory.row("emails", email_id)
    assert row["processing_status"] == "pending"
    assert row["processing_error"] == "Test error"
    assert row["locked_by"] is None


def test_stale_email_worker_cannot_fail_new_generation(db, factory, user):
    email_id = make_email(factory, user)
    first = emails.claim_unprocessed_email(db, "worker-a")
    set_cols(db, "emails", email_id, locked_until=ts(-1))
    second = emails.claim_unprocessed_email(db, "worker-b")
    assert second["id"] == email_id

    result = emails.fail_email_processing(db, email_id, "worker-a", first["lock_generation"],
                                          "stale-worker", "stale", 1, 2)
    assert result == {"fenced": True, "status": "processing"}
    current = factory.row("emails", email_id)
    assert current["locked_by"] == "worker-b"
    assert current["lock_generation"] == second["lock_generation"]


def test_same_worker_with_old_generation_is_fenced(db, factory, user):
    email_id = make_email(factory, user)
    first = emails.claim_unprocessed_email(db, "worker-a")
    set_cols(db, "emails", email_id, locked_until=ts(-1))
    emails.claim_unprocessed_email(db, "worker-a")
    result = emails.fail_email_processing(db, email_id, "worker-a", first["lock_generation"], "x", None, 1, 2)
    assert result["fenced"] is True
    assert factory.row("emails", email_id)["processing_status"] == "processing"


def test_unleased_row_fences_any_caller(db, factory, user):
    """locked_by NULL IS DISTINCT FROM 'w': fenced, not a crash."""
    email_id = make_email(factory, user)
    assert emails.fail_email_processing(db, email_id, "w", 0, "x", None, 1, 2) == {
        "fenced": True, "status": "pending"}


def test_failure_backoff_grows_and_stays_capped(db, factory, user):
    email_id = make_email(factory, user, max_attempts=10)
    deltas = []
    for _ in range(5):
        claimed = emails.claim_unprocessed_email(db, "worker-a")
        assert claimed["id"] == email_id
        result = emails.fail_email_processing(db, email_id, "worker-a", claimed["lock_generation"],
                                              "provider-transient", "d", 60, 300)
        assert result["status"] == "pending"
        deltas.append(round((codec.parse_timestamp(result["next_retry_at"]) - datetime.now(timezone.utc)).total_seconds()))
        set_cols(db, "emails", email_id, next_retry_at=ts(-1))
    # 60 * 2^(attempts-1) capped at 300
    assert deltas == [60, 120, 240, 300, 300]


def test_terminal_failure_dead_letters(db, factory, user):
    email_id = make_email(factory, user, max_attempts=1)
    claimed = emails.claim_unprocessed_email(db, "w")
    long_code = "e" * 150
    result = emails.fail_email_processing(db, email_id, "w", claimed["lock_generation"], long_code, "d", 1, 2)
    assert result == {"fenced": False, "status": "failed", "attempts": 1}
    row = factory.row("emails", email_id)
    assert row["processing_status"] == "failed"
    assert row["processing_error"] == "e" * 100
    assert row["dead_letter_reason"] == "e" * 100
    assert row["dead_letter_at"] is not None
    assert row["locked_by"] is None


def test_fail_unknown_email_raises_not_found(db):
    with pytest.raises(NotFound):
        emails.fail_email_processing(db, codec.new_id(), "w", 1, "x", None, 1, 2)


def test_null_retry_settings_behave_like_greatest(db, factory, user):
    email_id = make_email(factory, user)
    claimed = emails.claim_unprocessed_email(db, "w")
    result = emails.fail_email_processing(db, email_id, "w", claimed["lock_generation"], "x", None, None, None)
    delta = (codec.parse_timestamp(result["next_retry_at"]) - datetime.now(timezone.utc)).total_seconds()
    assert 0 < delta <= 1.01


# --- reprocess_email -------------------------------------------------------------


def test_reprocess_resets_any_unleased_terminal_or_legacy_pending_row(db, factory, user):
    exhausted = make_email(factory, user, processing_status="failed", attempts=3, max_attempts=3,
                           dead_letter_reason="legacy_attempts_exhausted", dead_letter_at=ts(-5),
                           processing_outcome="no_event", processing_result={"a": 1})
    legacy_pending = make_email(factory, user, processing_status="pending", attempts=1, max_attempts=3)
    for row_id in (exhausted, legacy_pending):
        result = emails.reprocess_email(db, user, row_id)
        assert result["id"] == row_id
    for row_id in (exhausted, legacy_pending):
        row = factory.row("emails", row_id)
        assert row["processing_status"] == "pending"
        assert row["attempts"] == 0
        assert row["locked_by"] is None and row["locked_until"] is None and row["next_retry_at"] is None
        assert row["dead_letter_reason"] is None and row["processing_outcome"] is None
        assert row["processing_result"] is None
        assert row["lock_generation"] == 1


def test_reprocess_refuses_an_actively_leased_row(db, factory, user):
    email_id = make_email(factory, user)
    emails.claim_unprocessed_email(db, "live-worker")
    with pytest.raises(EmailActivelyLeased):
        emails.reprocess_email(db, user, email_id)
    assert factory.row("emails", email_id)["locked_by"] == "live-worker"


def test_reprocess_accepts_an_expired_lease(db, factory, user):
    email_id = make_email(factory, user, processing_status="processing", attempts=1,
                          locked_by="dead", locked_until=ts(-1))
    assert emails.reprocess_email(db, user, email_id)["processing_status"] == "pending"


def test_reprocess_another_users_email_returns_none(db, factory, user):
    other = factory.user()
    email_id = make_email(factory, other, processing_status="failed")
    assert emails.reprocess_email(db, user, email_id) is None
    assert factory.row("emails", email_id)["processing_status"] == "failed"
    assert emails.reprocess_email(db, user, codec.new_id()) is None


# --- unlock_expired_email_locks ---------------------------------------------------


def test_unlock_expired_email_locks_retries_and_terminates_correctly(db, factory, user):
    retryable = make_email(factory, user, processing_status="processing", attempts=1, max_attempts=3,
                           locked_by="dead-a", locked_until=ts(-1))
    exhausted = make_email(factory, user, processing_status="processing", attempts=3, max_attempts=3,
                           locked_by="dead-b", locked_until=ts(-1))
    live = make_email(factory, user, processing_status="processing", attempts=1,
                      locked_by="live", locked_until=ts(300))
    assert emails.unlock_expired_email_locks(db) == 1
    assert factory.row("emails", retryable)["processing_status"] == "pending"
    assert factory.row("emails", retryable)["locked_by"] is None
    row = factory.row("emails", exhausted)
    assert row["processing_status"] == "failed"
    assert row["dead_letter_reason"] == "lease_expired_at_limit"
    assert row["locked_by"] is None
    assert factory.row("emails", live)["locked_by"] == "live"


def test_email_lock_expiry_recovery(db, factory, user):
    make_email(factory, user)
    emails.claim_unprocessed_email(db, "worker-1", 1)
    with db.write() as tx:
        tx.execute("UPDATE emails SET locked_until = ?", (ts(-10),))
    assert emails.unlock_expired_email_locks(db) == 1
    assert emails.claim_unprocessed_email(db, "worker-2") is not None


# --- complete / reads -------------------------------------------------------------


def test_email_claim_complete_roundtrip(db, factory, user):
    email_id = make_email(factory, user)
    assert emails.claim_unprocessed_email(db, "w", 120)["id"] == email_id
    assert emails.complete_email_processing(db, email_id) is True
    row = factory.row("emails", email_id)
    assert row["processing_status"] == "processed"
    assert row["processed_at"] is not None and row["locked_by"] is None


def test_get_email_is_user_scoped(db, factory, user):
    email_id = make_email(factory, user)
    assert emails.get_email(db, user, email_id)["id"] == email_id
    assert emails.get_email(db, factory.user(), email_id) is None
    assert emails.get_for_extraction(db, email_id)["provider_labels"] == ["INBOX"]
    assert emails.get_for_extraction(db, codec.new_id()) is None


def test_active_mail_integrations_and_request_poll(db, factory, user):
    gmail = factory.integration(user, "gmail")
    factory.integration(user, "outlook", status="expired")
    factory.integration(user, "google_calendar")
    assert emails.active_mail_integrations(db, user) == [{"id": gmail, "provider": "gmail"}]

    future = ts(3600)
    with db.write() as tx:
        tx.execute("UPDATE email_sync_state SET next_poll_at = ? WHERE integration_id = ?", (future, gmail))
    assert emails.request_poll(db, gmail) is True
    state = db.query_one("SELECT next_poll_at FROM email_sync_state WHERE integration_id = ?", (gmail,))
    assert state["next_poll_at"] < future

    with db.write() as tx:
        tx.execute("UPDATE email_sync_state SET next_poll_at = ?, lease_owner = 'w', lease_expires_at = ?"
                   " WHERE integration_id = ?", (future, future, gmail))
    assert emails.request_poll(db, gmail) is False  # a live run is left alone


# --- save_email_with_attachment_descriptors --------------------------------------


def test_save_returns_uuid_and_inserts_pending_email(db, user):
    db.signals = Recorder()
    email_id = emails.save_email_with_attachment_descriptors(
        db, user, {"email_provider": "gmail", "provider_message_id": "m1", "subject": "probe",
                   "user_id": "ignored-overridden"},
        [{"provider_attachment_id": "att", "filename": "p.pdf", "mime_type": "application/pdf", "size_bytes": 10}],
    )
    assert codec.to_id(email_id) == email_id
    row = db.schema.decode("emails", db.query_one("SELECT * FROM emails WHERE id = ?", (email_id,)))
    assert row["user_id"] == user and row["processing_status"] == "pending"
    assert set(db.signals.sent) == {"email_pending", "attachment_pending"}


def test_save_updates_only_supplied_columns(db, user):
    base = {"email_provider": "gmail", "provider_message_id": "m1"}
    first = emails.save_email_with_attachment_descriptors(
        db, user, {**base, "subject": "s", "body_text": "the full body"}, [])
    with db.write() as tx:
        tx.execute("UPDATE emails SET processing_status = 'processed' WHERE id = ?", (first,))
    second = emails.save_email_with_attachment_descriptors(db, user, {**base, "subject": "s2"}, [])
    assert second == first
    row = db.query_one("SELECT subject, body_text, processing_status FROM emails WHERE id = ?", (first,))
    assert (row["subject"], row["body_text"], row["processing_status"]) == ("s2", "the full body", "processed")


def test_save_coerces_types_like_jsonb_populate_record(db, user):
    email_id = emails.save_email_with_attachment_descriptors(
        db, user,
        {"email_provider": "gmail", "provider_message_id": "m1",
         "date_sent": "2026-11-25T10:00:00+02:00", "to_emails": ["a@b.c"],
         "provider_labels": ["INBOX", "UNREAD", "STARRED"], "provider_folder_ids": ["INBOX"],
         "has_attachments": "true", "is_calendar_invite": False},
        [],
    )
    row = db.schema.decode("emails", db.query_one("SELECT * FROM emails WHERE id = ?", (email_id,)))
    assert row["date_sent"] == "2026-11-25T08:00:00.000000Z"
    assert row["to_emails"] == ["a@b.c"]
    assert row["has_attachments"] is True and row["is_calendar_invite"] is False
    assert row["is_unread"] is True and row["is_starred"] is True and row["is_spam"] is False


def test_save_naive_date_sent_is_utc(db, user):
    email_id = emails.save_email_with_attachment_descriptors(
        db, user, {"email_provider": "gmail", "provider_message_id": "m", "date_sent": "2026-01-01T12:00:00"}, [])
    assert db.query_one("SELECT date_sent FROM emails WHERE id = ?", (email_id,))[0] == "2026-01-01T12:00:00.000000Z"


def test_save_requires_identity_and_a_settable_column(db, user):
    with pytest.raises(InvalidArgument):
        emails.save_email_with_attachment_descriptors(db, user, {"provider_message_id": "m"}, [])
    with pytest.raises(InvalidArgument):
        emails.save_email_with_attachment_descriptors(
            db, user, {"email_provider": "gmail", "provider_message_id": "m"}, [])
    with pytest.raises(NotNullViolation):
        emails.save_email_with_attachment_descriptors(
            db, user, {"email_provider": "gmail", "provider_message_id": "m", "provider_labels": None}, [])


def test_save_ignores_unknown_columns(db, user):
    email_id = emails.save_email_with_attachment_descriptors(
        db, user, {"email_provider": "gmail", "provider_message_id": "m", "subject": "s",
                   "processing_status": "processed", "id": "nope"}, [])
    row = db.query_one("SELECT id, processing_status FROM emails WHERE id = ?", (email_id,))
    assert row["processing_status"] == "pending"


def test_descriptor_fallbacks_and_filtering(db, user):
    email_id = emails.save_email_with_attachment_descriptors(
        db, user, {"email_provider": "gmail", "provider_message_id": "m", "subject": "s"},
        [{"provider_attachment_id": "a", "name": "n.txt", "contentType": "text/plain", "size": "7"},
         {"provider_attachment_id": "b", "filename": "", "mime_type": ""},
         {"provider_attachment_id": ""}, {"filename": "no-id"}, "not-an-object",
         {"provider_attachment_id": "a", "filename": "duplicate"}],
    )
    rows = {r["provider_attachment_id"]: dict(r) for r in db.query(
        "SELECT provider_attachment_id, filename, mime_type, size_bytes, ingestion_status, user_id"
        " FROM attachments WHERE email_id = ?", (email_id,))}
    assert set(rows) == {"a", "b"}
    assert (rows["a"]["filename"], rows["a"]["mime_type"], rows["a"]["size_bytes"]) == ("n.txt", "text/plain", 7)
    assert (rows["b"]["filename"], rows["b"]["mime_type"], rows["b"]["size_bytes"]) == (
        "unnamed", "application/octet-stream", 0)
    assert all(r["user_id"] == user for r in rows.values())


def test_descriptor_bad_size_rolls_back_everything(db, user):
    with pytest.raises(InvalidArgument):
        emails.save_email_with_attachment_descriptors(
            db, user, {"email_provider": "gmail", "provider_message_id": "m", "subject": "s"},
            [{"provider_attachment_id": "a", "size_bytes": 12.5}])
    assert db.query_one("SELECT count(*) FROM emails")[0] == 0


def test_re_acquired_email_keeps_existing_attachment_rows_unreset(db, factory, user):
    integration = factory.integration(user)
    payload = {"email_provider": "gmail", "provider_message_id": "reacq", "subject": "re-acquire",
               "date_sent": ts(), "provider_labels": ["INBOX"], "has_attachments": True,
               "integration_id": integration}
    descriptors = [{"provider_attachment_id": "att-1", "filename": "a.txt", "mime_type": "text/plain", "size_bytes": 10},
                   {"provider_attachment_id": "att-2", "filename": "b.pdf", "mime_type": "application/pdf", "size_bytes": 200}]
    email_id = emails.save_email_with_attachment_descriptors(db, user, payload, descriptors)
    with db.write() as tx:
        tx.execute("UPDATE attachments SET ingestion_status = 'stored', storage_path = 'path/a.txt'"
                   " WHERE email_id = ? AND provider_attachment_id = 'att-1'", (email_id,))
    assert emails.save_email_with_attachment_descriptors(db, user, payload, descriptors) == email_id
    by_id = {r[0]: r[1] for r in db.query(
        "SELECT provider_attachment_id, ingestion_status FROM attachments WHERE email_id = ?", (email_id,))}
    assert by_id == {"att-1": "stored", "att-2": "pending"}


def test_calendar_components_survive_empty_resave(db, user):
    payload = {"email_provider": "gmail", "provider_message_id": "cal", "subject": "probe",
               "from_email": "calendar-component@example.com", "provider_labels": ["INBOX"]}
    component = {"method": "CANCEL", "uid_hash": "a" * 64, "sequence": 4, "component_status": "CANCELLED",
                 "start_datetime": "2026-08-20T13:00:00Z", "end_datetime": "2026-08-20T14:00:00Z",
                 "dtstamp": ""}
    email_id = emails.save_email_with_attachment_descriptors(db, user, payload, [], [component])
    rows = [dict(r) for r in db.query(
        "SELECT method, uid_hash, sequence, component_status, component_index, start_datetime, dtstamp, user_id"
        " FROM email_calendar_components WHERE email_id = ?", (email_id,))]
    assert rows == [{"method": "CANCEL", "uid_hash": "a" * 64, "sequence": 4, "component_status": "CANCELLED",
                     "component_index": 0, "start_datetime": "2026-08-20T13:00:00.000000Z",
                     "dtstamp": None, "user_id": user}]

    emails.save_email_with_attachment_descriptors(db, user, payload, [], [])
    emails.save_email_with_attachment_descriptors(db, user, payload, [], None)
    assert db.query_one("SELECT count(*) FROM email_calendar_components WHERE email_id = ?", (email_id,))[0] == 1

    emails.save_email_with_attachment_descriptors(
        db, user, payload, [], [{"method": "REQUEST"}, {"method": "REQUEST", "sequence": ""}])
    rows = db.query("SELECT component_index, method, sequence FROM email_calendar_components"
                    " WHERE email_id = ? ORDER BY component_index", (email_id,))
    assert [tuple(r) for r in rows] == [(0, "REQUEST", 0), (1, "REQUEST", 0)]


def test_component_without_method_fails_the_whole_save(db, user):
    with pytest.raises(NotNullViolation):
        emails.save_email_with_attachment_descriptors(
            db, user, {"email_provider": "gmail", "provider_message_id": "m", "subject": "s"}, [], [{}])
    assert db.query_one("SELECT count(*) FROM emails")[0] == 0


# --- reads and writes added for the services (wire/email-ingestion) ----------


def test_owned_reads_never_cross_users(db, factory, user):
    other = factory.user()
    mine = factory.email(user, date_sent="2026-01-01T00:00:00.000000Z")
    newer = factory.email(user, date_sent="2026-02-01T00:00:00.000000Z")
    undated = factory.email(user)
    theirs = factory.email(other, date_sent="2026-03-01T00:00:00.000000Z")

    assert emails.exists_owned(db, user, mine) is True
    assert emails.exists_owned(db, user, theirs) is False
    assert emails.exists_owned(db, user, "nonexistent-id") is False
    assert emails.reprocess_email(db, user, "nonexistent-id") is None
    # PostgREST's order(desc) put NULLs first; the port keeps that.
    assert emails.list_ids_recent(db, user, 10) == [undated, newer, mine]
    assert emails.list_ids_recent(db, user, 1) == [undated]


def test_acquisition_context_names_the_owner_and_provider(db, factory, user):
    integration = factory.integration(user)
    email_id = factory.email(user, email_provider="gmail", integration_id=integration)

    assert emails.acquisition_context(db, email_id) == {
        "user_id": user, "email_provider": "gmail",
        "provider_message_id": factory.row("emails", email_id)["provider_message_id"],
        "integration_id": integration,
    }
    assert emails.acquisition_context(db, codec.new_id()) is None


