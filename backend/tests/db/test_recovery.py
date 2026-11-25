"""selko.db.recovery against a real SQLite database.

Ports the assertions of integration/test_integration_recovery.py and
integration/test_integration_calendar_recovery_worker.py, plus the edge cases
the Postgres functions define (provider routing, the newer-item guard, the
outlook calendar scope, batch limits).
"""

from __future__ import annotations

import pytest

from selko.db import errors, recovery
from selko.db.codec import new_id


def _reauth(db, user_id, provider="google_calendar", **kw):
    args = dict(access_token="access-1", refresh_token="refresh-1", token_expiry=None,
                scopes=["calendar"], provider_email=None)
    args.update(kw)
    return recovery.complete_integration_reauthorization(db, user_id, provider, **args)


def _recoveries(db, user_id):
    return [db.schema.decode("integration_recoveries", r) for r in db.query(
        "SELECT * FROM integration_recoveries WHERE user_id = ? ORDER BY requested_at", (user_id,))]


def _set(db, table, row_id, **fields):
    cols = ", ".join(f"{k} = ?" for k in fields)
    with db.write() as tx:
        tx.execute(f"UPDATE {table} SET {cols} WHERE id = ?", (*fields.values(), row_id))


def _blocked_event(db, factory, user_id, failure_code="oauth_required", status="failed",
                   provider=None, **event_extra):
    event_id = factory.event(user_id, review_status="active", **event_extra)
    item = {"id": new_id(), "event_id": event_id, "user_id": user_id, "action": "upsert",
            "generation": 1, "status": status if failure_code else "pending",
            "desired_event": {"title": "Recovery worker test event"},
            "failure_code": failure_code}
    if provider:
        item["provider"] = provider
    factory._insert("calendar_work_items", item)
    return event_id, item["id"]


def _create_and_claim(db, user_id):
    _reauth(db, user_id)
    return recovery.claim_integration_recovery(db, "worker-1", lock_seconds=120)


# --- 49 complete_integration_reauthorization ---------------------------------


class TestCompleteIntegrationReauthorization:
    def test_upserts_credentials_and_creates_calendar_recovery(self, db, factory):
        user = factory.user()
        integration_id = _reauth(db, user)

        integration = db.schema.decode("integrations", db.query_one(
            "SELECT * FROM integrations WHERE user_id = ? AND provider = 'google_calendar'", (user,)))
        assert integration["id"] == integration_id
        assert integration["status"] == "active"
        assert integration["access_token"] == "access-1"
        assert integration["scopes"] == ["calendar"]

        rows = _recoveries(db, user)
        assert len(rows) == 1
        assert rows[0]["status"] == "pending"
        assert rows[0]["reason"] == "reauthorization"
        assert rows[0]["integration_id"] == integration_id
        assert rows[0]["provider"] == "google_calendar"

    def test_preserves_existing_refresh_token_and_email_when_omitted(self, db, factory):
        user = factory.user()
        first = _reauth(db, user, provider_email="a@example.test")
        second = _reauth(db, user, access_token="access-2", refresh_token=None, provider_email=None)
        assert first == second

        integration = factory.row("integrations", first)
        assert integration["access_token"] == "access-2"
        assert integration["refresh_token"] == "refresh-1"
        assert integration["provider_email"] == "a@example.test"

    def test_reactivates_an_expired_integration_and_replaces_scopes(self, db, factory):
        user = factory.user()
        integration_id = factory.integration(user, provider="google_calendar", status="expired",
                                             scopes=["old"])
        assert _reauth(db, user, scopes=None) == integration_id
        row = factory.row("integrations", integration_id)
        assert row["status"] == "active"
        assert row["scopes"] == []

    def test_repeated_reauthorization_supersedes_previous_recovery(self, db, factory):
        user = factory.user()
        _reauth(db, user)
        _reauth(db, user, access_token="access-2", refresh_token=None)
        assert sorted(r["status"] for r in _recoveries(db, user)) == ["pending", "superseded"]

    def test_supersession_releases_the_lease(self, db, factory):
        user = factory.user()
        claimed = _create_and_claim(db, user)
        _reauth(db, user, access_token="access-2")
        old = factory.row("integration_recoveries", claimed["id"])
        assert old["status"] == "superseded"
        assert old["locked_by"] is None and old["locked_until"] is None

    def test_gmail_reauthorization_creates_no_recovery_but_a_sync_state(self, db, factory):
        user = factory.user()
        integration_id = _reauth(db, user, provider="gmail", scopes=["gmail.readonly"])
        assert _recoveries(db, user) == []
        state = db.query_one("SELECT * FROM email_sync_state WHERE integration_id = ?", (integration_id,))
        assert state is not None

    @pytest.mark.parametrize("scopes, expected", [
        (["Mail.Read", "https://graph.microsoft.com/Calendars.ReadWrite"], 1),
        (["Mail.Read", "calendars.readwrite"], 1),
        (["Mail.Read"], 0),
        (["Calendars.ReadWrite.Shared"], 0),
    ])
    def test_outlook_creates_recovery_only_with_calendar_scope(self, db, factory, scopes, expected):
        user = factory.user()
        _reauth(db, user, provider="outlook", scopes=scopes)
        assert len(_recoveries(db, user)) == expected

    def test_rejects_unknown_provider(self, db, factory):
        user = factory.user()
        with pytest.raises(errors.InvalidArgument):
            _reauth(db, user, provider="dropbox")

    def test_token_expiry_is_stored_in_codec_form(self, db, factory):
        user = factory.user()
        integration_id = _reauth(db, user, token_expiry="2026-12-01T10:00:00+02:00")
        assert factory.row("integrations", integration_id)["token_expiry"] == "2026-12-01T08:00:00.000000Z"


# --- 50 claim / 53 unlock ------------------------------------------------------


class TestClaimIntegrationRecovery:
    def test_claim_locks_row_and_increments_attempts(self, db, factory):
        user = factory.user()
        _reauth(db, user)
        claimed = recovery.claim_integration_recovery(db, "worker-1", lock_seconds=300)
        assert claimed is not None
        assert claimed["status"] == "processing"
        assert claimed["locked_by"] == "worker-1"
        assert claimed["attempts"] == 1
        assert claimed["started_at"] is not None
        assert claimed["locked_until"] > claimed["started_at"]
        # Already claimed: a second worker must not also get it.
        assert recovery.claim_integration_recovery(db, "worker-2") is None

    def test_claim_returns_none_when_nothing_pending(self, db):
        assert recovery.claim_integration_recovery(db, "worker-1") is None

    def test_claims_oldest_first(self, db, factory):
        first_user, second_user = factory.user(), factory.user()
        first = _reauth(db, first_user)
        _reauth(db, second_user)
        claimed = recovery.claim_integration_recovery(db, "w")
        assert claimed["integration_id"] == first

    def test_reclaims_processing_recovery_with_expired_lock(self, db, factory):
        user = factory.user()
        claimed = _create_and_claim(db, user)
        started = claimed["started_at"]
        _set(db, "integration_recoveries", claimed["id"], locked_until="2020-01-01T00:00:00.000000Z")

        reclaimed = recovery.claim_integration_recovery(db, "worker-2", lock_seconds=120)
        assert reclaimed["id"] == claimed["id"]
        assert reclaimed["status"] == "processing"
        assert reclaimed["locked_by"] == "worker-2"
        assert reclaimed["attempts"] == 2
        assert reclaimed["started_at"] == started  # COALESCE keeps the first start

    def test_exhausted_or_backing_off_rows_are_not_claimed(self, db, factory):
        user = factory.user()
        _reauth(db, user)
        rec = _recoveries(db, user)[0]
        _set(db, "integration_recoveries", rec["id"], attempts=5)
        assert recovery.claim_integration_recovery(db, "w") is None
        _set(db, "integration_recoveries", rec["id"], attempts=0, next_retry_at="2999-01-01T00:00:00.000000Z")
        assert recovery.claim_integration_recovery(db, "w") is None
        _set(db, "integration_recoveries", rec["id"], next_retry_at="2000-01-01T00:00:00.000000Z")
        assert recovery.claim_integration_recovery(db, "w") is not None

    def test_waiting_rows_are_not_claimed(self, db, factory):
        user = factory.user()
        _reauth(db, user)
        _set(db, "integration_recoveries", _recoveries(db, user)[0]["id"], status="waiting")
        assert recovery.claim_integration_recovery(db, "w") is None

    def test_unlock_expired_returns_locked_rows_to_pending(self, db, factory):
        user = factory.user()
        claimed = _create_and_claim(db, user)
        _set(db, "integration_recoveries", claimed["id"], locked_until="2000-01-01T00:00:00.000000Z")

        assert recovery.unlock_expired_integration_recoveries(db) == 1
        row = factory.row("integration_recoveries", claimed["id"])
        assert row["status"] == "pending"
        assert row["locked_by"] is None
        assert row["locked_until"] is None
        assert recovery.unlock_expired_integration_recoveries(db) == 0

    def test_unlock_leaves_live_leases(self, db, factory):
        user = factory.user()
        _create_and_claim(db, user)
        assert recovery.unlock_expired_integration_recoveries(db) == 0


# --- 51 requeue ----------------------------------------------------------------


class TestRequeueCalendarRecoveryBatch:
    def test_tags_only_oauth_blocked_events(self, db, factory):
        user = factory.user()
        oauth_event, oauth_item = _blocked_event(db, factory, user, "oauth_required")
        scope_event, _ = _blocked_event(db, factory, user, "oauth_scope_required", status="blocked")
        untouched_event, untouched_item = _blocked_event(db, factory, user, "permission_denied")
        no_code_event, _ = _blocked_event(db, factory, user, None)

        rec = _create_and_claim(db, user)
        assert recovery.requeue_calendar_recovery_batch(db, rec["id"], "worker-1") == 2

        tagged = {r[0] for r in db.query("SELECT id FROM events WHERE recovery_id = ?", (rec["id"],))}
        assert tagged == {oauth_event, scope_event}

        item = factory.row("calendar_work_items", oauth_item)
        assert item["status"] == "pending"
        assert item["locked_by"] is None and item["next_retry_at"] is None
        assert factory.row("calendar_work_items", untouched_item)["status"] == "failed"

        row = factory.row("integration_recoveries", rec["id"])
        assert row["status"] == "waiting"
        assert row["discovered_count"] == 2 and row["requeued_count"] == 2
        assert row["remaining_count"] == 2
        assert row["locked_by"] is None and row["locked_until"] is None

    def test_returns_negative_one_when_claim_lost(self, db, factory):
        user = factory.user()
        rec = _create_and_claim(db, user)
        assert recovery.requeue_calendar_recovery_batch(db, rec["id"], "a-different-worker") == -1

    def test_expired_lease_is_lost(self, db, factory):
        user = factory.user()
        rec = _create_and_claim(db, user)
        _set(db, "integration_recoveries", rec["id"], locked_until="2000-01-01T00:00:00.000000Z")
        assert recovery.requeue_calendar_recovery_batch(db, rec["id"], "worker-1") == -1

    def test_superseded_recovery_cannot_be_requeued_by_old_worker(self, db, factory):
        user = factory.user()
        rec = _create_and_claim(db, user)
        _reauth(db, user, access_token="access-2", refresh_token=None)
        assert recovery.requeue_calendar_recovery_batch(db, rec["id"], "worker-1", 10, 1) == -1
        assert sorted(r["status"] for r in _recoveries(db, user)) == ["pending", "superseded"]

    def test_attempts_are_capped_below_max(self, db, factory):
        user = factory.user()
        _, item_id = _blocked_event(db, factory, user)
        _set(db, "calendar_work_items", item_id, attempts=3)
        rec = _create_and_claim(db, user)
        recovery.requeue_calendar_recovery_batch(db, rec["id"], "worker-1")
        assert factory.row("calendar_work_items", item_id)["attempts"] == 2

    def test_skips_event_with_a_newer_active_item(self, db, factory):
        user = factory.user()
        event_id, _ = _blocked_event(db, factory, user)
        factory._insert("calendar_work_items", {
            "id": new_id(), "event_id": event_id, "user_id": user, "action": "upsert",
            "generation": 2, "status": "pending"})
        rec = _create_and_claim(db, user)
        assert recovery.requeue_calendar_recovery_batch(db, rec["id"], "worker-1") == 0

    def test_ignores_other_users_events_and_already_tagged_events(self, db, factory):
        user, other = factory.user(), factory.user()
        _blocked_event(db, factory, other)
        rec = _create_and_claim(db, user)
        assert recovery.requeue_calendar_recovery_batch(db, rec["id"], "worker-1") == 0

    def test_only_items_routed_to_the_recovery_provider(self, db, factory):
        user = factory.user()
        google_event, _ = _blocked_event(db, factory, user)  # routes to google (connected)
        outlook_stamped, _ = _blocked_event(db, factory, user, provider="outlook")
        outlook_existing, _ = _blocked_event(db, factory, user, google_calendar_event_id="outlook:abc")
        rec = _create_and_claim(db, user)
        assert recovery.requeue_calendar_recovery_batch(db, rec["id"], "worker-1") == 1
        tagged = {r[0] for r in db.query("SELECT id FROM events WHERE recovery_id = ?", (rec["id"],))}
        assert tagged == {google_event}

    def test_target_calendar_routes_unstamped_items(self, db, factory):
        user = factory.user()
        factory._insert("user_calendar_settings",
                        {"user_id": user, "target_calendar_id": "outlook:cal-1"})
        _blocked_event(db, factory, user)
        rec = _create_and_claim(db, user)
        assert recovery.requeue_calendar_recovery_batch(db, rec["id"], "worker-1") == 0

    def test_batches_are_bounded(self, db, factory):
        user = factory.user()
        for _ in range(5):
            _blocked_event(db, factory, user)
        rec = _create_and_claim(db, user)
        # 2 per batch, at most 2 batches: 4 of 5.
        assert recovery.requeue_calendar_recovery_batch(db, rec["id"], "worker-1", 2, 2) == 4
        assert factory.row("integration_recoveries", rec["id"])["remaining_count"] == 4

    def test_negative_batch_size_is_refused(self, db, factory):
        user = factory.user()
        rec = _create_and_claim(db, user)
        with pytest.raises(errors.InvalidArgument):
            recovery.requeue_calendar_recovery_batch(db, rec["id"], "worker-1", -1)


# --- 52 refresh ----------------------------------------------------------------


class TestRefreshWaitingCalendarRecoveries:
    def _tagged(self, db, factory):
        user = factory.user()
        event_id, item_id = _blocked_event(db, factory, user)
        rec = _create_and_claim(db, user)
        recovery.requeue_calendar_recovery_batch(db, rec["id"], "worker-1")
        return rec, item_id

    def test_finalizes_completed_once_tagged_events_synced(self, db, factory):
        rec, item_id = self._tagged(db, factory)
        _set(db, "calendar_work_items", item_id, status="succeeded", provider_event_id="recovered")
        assert recovery.refresh_waiting_calendar_recoveries(db) == 1
        row = factory.row("integration_recoveries", rec["id"])
        assert row["status"] == "completed"
        assert row["completed_count"] == 1
        assert row["remaining_count"] == 0
        assert row["completed_at"] is not None
        # Finalized rows are not waiting any more.
        assert recovery.refresh_waiting_calendar_recoveries(db) == 0

    def test_finalizes_completed_with_errors_when_a_tagged_event_fails(self, db, factory):
        rec, item_id = self._tagged(db, factory)
        _set(db, "calendar_work_items", item_id, status="failed", failure_code="invalid_event")
        recovery.refresh_waiting_calendar_recoveries(db)
        assert factory.row("integration_recoveries", rec["id"])["status"] == "completed_with_errors"

    def test_still_waiting_while_tagged_event_is_unresolved(self, db, factory):
        rec, _ = self._tagged(db, factory)
        row = factory.row("integration_recoveries", rec["id"])
        assert row["status"] == "waiting"
        assert row["remaining_count"] == 1
        assert recovery.refresh_waiting_calendar_recoveries(db) == 1
        row = factory.row("integration_recoveries", rec["id"])
        assert row["status"] == "waiting" and row["remaining_count"] == 1

    def test_a_recovery_with_nothing_tagged_completes(self, db, factory):
        user = factory.user()
        rec = _create_and_claim(db, user)
        assert recovery.requeue_calendar_recovery_batch(db, rec["id"], "worker-1") == 0
        recovery.refresh_waiting_calendar_recoveries(db)
        assert factory.row("integration_recoveries", rec["id"])["status"] == "completed"

    def test_batch_size_bounds_and_orders_by_updated_at(self, db, factory):
        recs = []
        for _ in range(3):
            user = factory.user()
            rec = _create_and_claim(db, user)
            recovery.requeue_calendar_recovery_batch(db, rec["id"], "worker-1")
            recs.append(rec["id"])
        assert recovery.refresh_waiting_calendar_recoveries(db, batch_size=2) == 2
        statuses = [factory.row("integration_recoveries", r)["status"] for r in recs]
        assert statuses == ["completed", "completed", "waiting"]


def test_latest_recovery_is_the_newest_for_the_user(db, factory):
    user, other = factory.user(), factory.user()
    _reauth(db, user)
    _reauth(db, user, access_token="access-2")
    _reauth(db, other)
    latest = recovery.latest_recovery(db, user)
    assert latest["status"] == "pending"
    assert latest["user_id"] == user
    assert set(latest) == set(recovery.RECOVERY_CARD_COLUMNS)
    assert recovery.latest_recovery(db, factory.user()) is None
