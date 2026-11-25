"""selko.db.attachments against a real SQLite file.

Ported from integration/test_integration_worker_pool_port.py
(test_claim_and_finish_attachment, test_save_email_with_attachment_descriptors_returns_uuid)
and the services/attachments.py table call sites.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from selko.db import attachments, codec, emails
from selko.db.errors import InvalidArgument, NotNullViolation


def ts(delta_seconds: float = 0) -> str:
    return codec.to_timestamp(datetime.now(timezone.utc) + timedelta(seconds=delta_seconds))


@pytest.fixture
def user(factory):
    return factory.user()


@pytest.fixture
def email_id(factory, user):
    return factory.email(user)


def add(factory, user, email_id, **extra):
    values = {"id": codec.new_id(), "user_id": user, "email_id": email_id, "filename": "f.pdf"}
    values.update(extra)
    return factory._insert("attachments", values)


class Recorder:
    def __init__(self):
        self.sent = []

    def signal(self, work_type):
        self.sent.append(work_type)


def test_claim_and_finish_attachment(db, user):
    email = emails.save_email_with_attachment_descriptors(
        db, user, {"email_provider": "gmail", "provider_message_id": "c2-att", "subject": "probe"},
        [{"provider_attachment_id": "att-1", "filename": "probe.pdf", "mime_type": "application/pdf"}],
    )
    attachment = attachments.claim_email_attachment(db, "worker-6")
    assert attachment is not None
    json.dumps(attachment)
    assert isinstance(attachment["id"], str) and attachment["email_id"] == email
    assert attachment["ingestion_status"] == "processing"
    assert attachment["attempts"] == 1
    assert attachment["locked_by"] == "worker-6"
    assert codec.parse_timestamp(attachment["locked_until"]) - datetime.now(timezone.utc) > timedelta(seconds=890)

    db.signals = Recorder()
    assert attachments.finish_email_attachment(db, attachment["id"], "worker-6", "unsupported", "x" * 120) is True
    assert db.signals.sent == []  # parity: no email_pending wake-up on finish
    row = db.query_one("SELECT * FROM attachments WHERE id = ?", (attachment["id"],))
    assert row["ingestion_status"] == "unsupported"
    assert row["ingestion_error_code"] == "x" * 100
    assert row["locked_by"] is None and row["locked_until"] is None and row["next_retry_at"] is None
    assert attachments.claim_email_attachment(db, "worker-6") is None


def test_claim_order_and_due_filters(db, factory, user, email_id):
    later = add(factory, user, email_id, created_at=ts(-10))
    earliest = add(factory, user, email_id, created_at=ts(-20))
    add(factory, user, email_id, created_at=ts(-30), next_retry_at=ts(60), ingestion_status="retry")
    add(factory, user, email_id, created_at=ts(-40), attempts=8, max_attempts=8)
    add(factory, user, email_id, created_at=ts(-50), ingestion_status="stored")
    add(factory, user, email_id, created_at=ts(-60), ingestion_status="processing",
        locked_by="live", locked_until=ts(300))
    assert attachments.claim_email_attachment(db, "w")["id"] == earliest
    assert attachments.claim_email_attachment(db, "w")["id"] == later
    assert attachments.claim_email_attachment(db, "w") is None


def test_expired_processing_lease_is_claimable(db, factory, user, email_id):
    stale = add(factory, user, email_id, ingestion_status="processing", attempts=1,
                locked_by="dead", locked_until=ts(-1))
    claimed = attachments.claim_email_attachment(db, "new", 0)
    assert claimed["id"] == stale and claimed["attempts"] == 2 and claimed["locked_by"] == "new"
    assert codec.parse_timestamp(claimed["locked_until"]) > datetime.now(timezone.utc)


def test_finish_is_fenced_on_worker(db, factory, user, email_id):
    add(factory, user, email_id)
    claimed = attachments.claim_email_attachment(db, "owner")
    assert attachments.finish_email_attachment(db, claimed["id"], "intruder", "stored") is False
    assert attachments.finish_email_attachment(db, claimed["id"], None, "stored") is False
    assert db.query_one("SELECT ingestion_status FROM attachments WHERE id = ?", (claimed["id"],))[0] == "processing"


def test_finish_rejects_unknown_state(db, factory, user, email_id):
    add(factory, user, email_id)
    claimed = attachments.claim_email_attachment(db, "w")
    for bad in ("pending", "processing", "done"):
        with pytest.raises(InvalidArgument):
            attachments.finish_email_attachment(db, claimed["id"], "w", bad)
    # NULL slips past the check, as in Postgres, and fails the NOT NULL column.
    with pytest.raises(NotNullViolation):
        attachments.finish_email_attachment(db, claimed["id"], "w", None)
    assert attachments.finish_email_attachment(db, codec.new_id(), "w", None) is False


def test_retry_finish_makes_it_claimable_again(db, factory, user, email_id):
    add(factory, user, email_id)
    claimed = attachments.claim_email_attachment(db, "w")
    attachments.finish_email_attachment(db, claimed["id"], "w", "retry", "transient")
    assert attachments.claim_email_attachment(db, "w")["id"] == claimed["id"]


def test_two_threads_never_claim_the_same_attachment(db, factory, user, email_id):
    ids = {add(factory, user, email_id, provider_attachment_id=f"p{i}") for i in range(40)}
    claimed: list[str] = []
    lock = threading.Lock()

    def worker(name):
        while (row := attachments.claim_email_attachment(db, name)) is not None:
            with lock:
                claimed.append(row["id"])

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(claimed) == sorted(ids)






def test_insert_refuses_unknown_columns(db, user, email_id):
    with pytest.raises(InvalidArgument):
        attachments.insert(db, user, {"email_id": email_id, "filename": "f", "ingestion_status": "stored"})


def test_store_result_is_fenced_on_the_lock_holder(db, factory, user):
    email_id = factory.email(user)
    attachments.ensure_descriptors(db, email_id, user, [{"provider_attachment_id": "a", "mime_type": "image/png"}])
    claimed = attachments.claim_email_attachment(db, "owner", 900)

    assert attachments.store_result(db, claimed["id"], "zombie", storage_path="p", content_hash="h", size_bytes=1) is False
    assert attachments.store_result(db, claimed["id"], "owner", storage_path=f"{user}/x_a.png",
                                    content_hash="h", size_bytes=3) is True
    row = factory.row("attachments", claimed["id"])
    assert (row["storage_path"], row["content_hash"], row["size_bytes"]) == (f"{user}/x_a.png", "h", 3)


def test_insert_get_delete_are_user_scoped(db, factory, user, email_id):
    db.signals = Recorder()
    row = attachments.insert(db, user, {
        "email_id": email_id, "provider_attachment_id": "p", "filename": "a.png", "mime_type": "image/png",
        "size_bytes": 5, "storage_path": f"{user}/abc_a.png", "content_hash": "h1"})
    assert row["ingestion_status"] == "pending" and row["user_id"] == user
    assert db.signals.sent == ["attachment_pending"]
    other = factory.user()

    assert attachments.get(db, user, row["id"])["storage_path"] == f"{user}/abc_a.png"
    assert attachments.get(db, other, row["id"]) is None
    assert [a["id"] for a in attachments.for_email(db, email_id)] == [row["id"]]

    assert attachments.delete(db, other, row["id"]) is False
    assert attachments.delete(db, user, row["id"]) is True
    assert attachments.get(db, user, row["id"]) is None
