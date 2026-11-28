"""selko.db.startup.reset_leases_at_startup: every lease from a dead run is released."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from selko.db import codec, emails
from selko.db.startup import reset_leases_at_startup


def ts(delta_seconds: float = 0) -> str:
    return codec.to_timestamp(datetime.now(timezone.utc) + timedelta(seconds=delta_seconds))


# Validates: SEL-630
def test_every_lease_is_released(db, factory):
    user = factory.user()
    integration = factory.integration(user)
    live = ts(600)  # unexpired: a lease present at startup still belongs to a dead run

    retry_email = factory.email(user, processing_status="processing", attempts=1, locked_by="w",
                                locked_until=live, lock_generation=4)
    exhausted_email = factory.email(user, processing_status="processing", attempts=3, max_attempts=3,
                                    locked_by="w", locked_until=live)
    untouched_email = factory.email(user, processing_status="processed")

    event = factory.event(user, review_status="active")
    work = factory._insert("calendar_work_items", {
        "id": codec.new_id(), "event_id": event, "user_id": user, "action": "upsert", "generation": 3,
        "status": "processing", "attempts": 1, "locked_by": "w", "locked_until": live})

    item = factory._insert("email_ingestion_items", {
        "id": codec.new_id(), "integration_id": integration, "user_id": user, "provider": "gmail",
        "provider_message_id": "m1", "acquisition_status": "processing", "attempts": 1,
        "lease_owner": "w", "lease_expires_at": live})
    attachment = factory._insert("attachments", {
        "id": codec.new_id(), "user_id": user, "email_id": untouched_email, "filename": "f",
        "ingestion_status": "processing", "attempts": 1, "locked_by": "w", "locked_until": live})
    recovery = factory._insert("integration_recoveries", {
        "id": codec.new_id(), "integration_id": integration, "user_id": user, "provider": "gmail",
        "reason": "reauthorization", "status": "processing", "locked_by": "w", "locked_until": live})
    run = factory._insert("email_sync_runs", {
        "id": codec.new_id(), "integration_id": integration, "user_id": user, "provider": "gmail",
        "run_kind": "initial", "status": "running", "lease_generation": 2})
    with db.write() as tx:
        tx.execute("UPDATE email_sync_state SET lease_owner = 'w', lease_expires_at = ?, lease_generation = 2"
                   " WHERE integration_id = ?", (live, integration))

    counts = reset_leases_at_startup(db)
    assert counts == {
        "emails": 1, "emails_failed": 1, "calendar_work_items": 1, "email_ingestion_items": 1,
        "attachments": 1, "integration_recoveries": 1, "email_sync_state": 1, "email_sync_runs": 1,
    }

    e = factory.row("emails", retry_email)
    assert (e["processing_status"], e["locked_by"], e["locked_until"], e["lock_generation"]) == ("pending", None, None, 4)
    e = factory.row("emails", exhausted_email)
    assert (e["processing_status"], e["dead_letter_reason"], e["locked_by"]) == ("failed", "lease_expired_at_limit", None)
    assert factory.row("emails", untouched_email)["processing_status"] == "processed"

    w = factory.row("calendar_work_items", work)
    assert (w["status"], w["locked_by"], w["locked_until"], w["attempts"], w["generation"]) == ("pending", None, None, 1, 3)
    i = factory.row("email_ingestion_items", item)
    assert (i["acquisition_status"], i["lease_owner"], i["lease_expires_at"]) == ("retry", None, None)
    a = factory.row("attachments", attachment)
    assert (a["ingestion_status"], a["locked_by"], a["locked_until"]) == ("retry", None, None)
    r = factory.row("integration_recoveries", recovery)
    assert (r["status"], r["locked_by"]) == ("pending", None)
    s = db.query_one("SELECT * FROM email_sync_state WHERE integration_id = ?", (integration,))
    assert (s["lease_owner"], s["lease_expires_at"], s["lease_generation"]) == (None, None, 2)
    run_row = factory.row("email_sync_runs", run)
    assert run_row["status"] == "abandoned" and run_row["completed_at"] is not None

    # Released work is claimable at once; a second reset finds nothing.
    assert emails.claim_unprocessed_email(db, "fresh")["id"] == retry_email
    with db.write() as tx:
        tx.execute("UPDATE emails SET processing_status = 'processed', locked_by = NULL, locked_until = NULL")
    assert all(v == 0 for v in reset_leases_at_startup(db).values())


# Validates: SEL-630
def test_reset_on_an_empty_database(db):
    assert all(v == 0 for v in reset_leases_at_startup(db).values())
