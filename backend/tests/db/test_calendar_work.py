"""`selko.db.calendar_work` against a real SQLite database.

Ports the assertions of the Postgres suites that exercised the calendar work
functions (integration/test_integration_calendar_work_items.py,
test_integration_automatic_cancellation.py, test_integration_outlook_calendar.py,
the calendar parts of test_integration_workers.py and
test_integration_extraction_intent.py, and the fail/defer behaviour the
mocked test_reliability.py only named), plus the edge cases of the Postgres
definitions: fencing, routing, claim order, starvation, backoff.
"""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from selko.db import calendar_work as cw
from selko.db.codec import parse_timestamp, to_json, to_timestamp, utc_now
from selko.db.errors import (
    InvalidArgument,
    InvariantViolation,
    NotNullViolation,
    NotOwned,
)

OUTLOOK_CALENDAR_SCOPES = ["Mail.Read", "User.Read", "Calendars.ReadWrite"]
OUTLOOK_MAIL_ONLY = ["Mail.Read", "User.Read"]


def _desired(title: str = "S2 event") -> dict:
    return {
        "title": title,
        "start_datetime": "2026-09-01T14:00:00Z",
        "end_datetime": "2026-09-01T15:00:00Z",
        "all_day": False,
        "location": "Test room",
        "description": "S2 integration probe",
        "importance": "action_required",
        "source_attribution": None,
    }


@pytest.fixture
def user(factory):
    """A user with an active Google Calendar integration."""
    user_id = factory.user()
    factory.integration(user_id, provider="google_calendar")
    return user_id


def _item(db, item_id):
    return db.schema.decode(
        "calendar_work_items", db.query_one("SELECT * FROM calendar_work_items WHERE id = ?", (item_id,))
    )


def _items_for(db, event_id):
    return [
        db.schema.decode("calendar_work_items", r)
        for r in db.query(
            "SELECT * FROM calendar_work_items WHERE event_id = ? ORDER BY generation", (event_id,)
        )
    ]


def _event(db, event_id):
    return db.schema.decode("events", db.query_one("SELECT * FROM events WHERE id = ?", (event_id,)))


def _set(db, table, row_id, **values):
    values = db.schema.encode(table, values)
    cols = ", ".join(f"{c} = ?" for c in values)
    with db.write() as tx:
        tx.execute(f"UPDATE {table} SET {cols} WHERE id = ?", (*values.values(), row_id))


def _set_scopes(db, user_id, provider, scopes):
    with db.write() as tx:
        tx.execute(
            "UPDATE integrations SET scopes = ? WHERE user_id = ? AND provider = ?",
            (to_json(scopes), user_id, provider),
        )


def _target(db, user_id, calendar_id):
    with db.write() as tx:
        tx.execute(
            "INSERT INTO user_calendar_settings (user_id, target_calendar_id) VALUES (?, ?) "
            "ON CONFLICT (user_id) DO UPDATE SET target_calendar_id = excluded.target_calendar_id",
            (user_id, calendar_id),
        )


def _approved(db, factory, user_id, google_calendar_event_id=None, title="Event"):
    event_id = factory.event(
        user_id, review_status="active", title=title, google_calendar_event_id=google_calendar_event_id
    )
    cw.enqueue_calendar_work(db, user_id, event_id, "upsert", {"title": title})
    return event_id


def _claim(db, worker="worker", lease=300, providers=None):
    return cw.claim_calendar_work_item(db, worker, lease, providers)


def _lease(item):
    return item["id"], item["locked_by"], item["generation"]


# ---------------------------------------------------------------------------
# enqueue
# ---------------------------------------------------------------------------


class TestEnqueue:
    def test_returns_the_postgres_shape(self, db, factory, user):
        event_id = factory.event(user, review_status="active")
        queued = cw.enqueue_calendar_work(db, user, event_id, "upsert", _desired())
        assert set(queued) == {"id", "event_id", "generation", "status", "action"}
        assert queued["event_id"] == event_id
        assert (queued["generation"], queued["status"], queued["action"]) == (1, "pending", "upsert")
        item = _item(db, queued["id"])
        assert item["desired_event"] == _desired()
        assert item["force_overwrite"] is False
        assert (item["attempts"], item["max_attempts"]) == (0, 3)
        assert item["provider"] is None
        assert item["completed_at"] is None

    def test_copies_the_events_calendar_id_and_bumps_the_event(self, db, factory, user):
        event_id = factory.event(user, review_status="active", google_calendar_event_id="g-1")
        before = _event(db, event_id)["updated_at"]
        queued = cw.enqueue_calendar_work(db, user, event_id, "upsert", {"title": "t"}, "rev-1", True)
        item = _item(db, queued["id"])
        assert item["provider_event_id"] == "g-1"
        assert item["expected_provider_revision"] == "rev-1"
        assert item["force_overwrite"] is True
        assert item["created_at"] == item["updated_at"]
        assert _event(db, event_id)["updated_at"] > before
        assert _event(db, event_id)["updated_at"] == item["created_at"]

    def test_new_generation_supersedes_the_active_item(self, db, factory, user):
        event_id = factory.event(user, review_status="active")
        first = cw.enqueue_calendar_work(db, user, event_id, "upsert", _desired("first"))
        second = cw.enqueue_calendar_work(db, user, event_id, "cancel")
        assert second["generation"] == 2
        old = _item(db, first["id"])
        assert old["status"] == "superseded"
        assert old["completed_at"] is not None
        assert [i["status"] for i in _items_for(db, event_id)] == ["superseded", "pending"]

    def test_generation_counts_every_item_including_terminal_ones(self, db, factory, user):
        event_id = factory.event(user, review_status="active")
        with db.write() as tx:
            tx.execute(
                "INSERT INTO calendar_work_items (id, event_id, user_id, action, generation, status) "
                "VALUES (?, ?, ?, 'upsert', 7, 'succeeded')",
                ("00000000-0000-0000-0000-0000000000a7", event_id, user),
            )
        assert cw.enqueue_calendar_work(db, user, event_id, "cancel")["generation"] == 8
        # A terminal item is not superseded.
        assert _item(db, "00000000-0000-0000-0000-0000000000a7")["status"] == "succeeded"

    @pytest.mark.parametrize("declined", ["rejected", "cancelled"])
    def test_upsert_is_refused_for_a_declined_event(self, db, factory, user, declined):
        """The queue helper no longer resurrects; it fails closed."""
        event_id = factory.event(user, review_status=declined)
        with pytest.raises(InvalidArgument, match="cannot queue calendar upsert"):
            cw.enqueue_calendar_work(db, user, event_id, "upsert", {"title": "Standup"})
        assert _event(db, event_id)["review_status"] == declined
        assert _items_for(db, event_id) == []

    @pytest.mark.parametrize("declined", ["rejected", "cancelled"])
    def test_cancel_is_allowed_for_a_declined_event(self, db, factory, user, declined):
        event_id = factory.event(user, review_status=declined)
        assert cw.enqueue_calendar_work(db, user, event_id, "cancel")["action"] == "cancel"

    def test_queueing_does_not_change_the_review_decision(self, db, factory, user):
        event_id = factory.event(user, review_status="pending_review")
        cw.enqueue_calendar_work(db, user, event_id, "upsert", {"title": "Standup"})
        assert _event(db, event_id)["review_status"] == "pending_review"
        assert [i["action"] for i in _items_for(db, event_id)] == ["upsert"]

    def test_invalid_action(self, db, factory, user):
        event_id = factory.event(user)
        with pytest.raises(InvalidArgument, match="invalid calendar work action delete"):
            cw.enqueue_calendar_work(db, user, event_id, "delete", {})

    def test_upsert_requires_desired_event(self, db, factory, user):
        event_id = factory.event(user, review_status="active")
        with pytest.raises(InvalidArgument, match="upsert calendar work requires desired_event"):
            cw.enqueue_calendar_work(db, user, event_id, "upsert", None)

    def test_null_action_fails_on_the_insert_and_rolls_back_the_supersede(self, db, factory, user):
        """Postgres: NULL NOT IN (...) is NULL, so the check passes and the insert fails."""
        event_id = factory.event(user, review_status="active")
        first = cw.enqueue_calendar_work(db, user, event_id, "cancel")
        with pytest.raises(NotNullViolation):
            cw.enqueue_calendar_work(db, user, event_id, None)
        assert _item(db, first["id"])["status"] == "pending"

    def test_not_owned(self, db, factory, user):
        other = factory.user()
        event_id = factory.event(other, review_status="active")
        with pytest.raises(NotOwned, match=f"event {event_id} is not owned by user {user}"):
            cw.enqueue_calendar_work(db, user, event_id, "cancel")
        with pytest.raises(NotOwned):
            cw.enqueue_calendar_work(db, user, "00000000-0000-0000-0000-00000000dead", "cancel")

    def test_enqueue_wakes_the_calendar_workers_after_commit(self, db, factory, user):
        """02 §0.3: Postgres never sent event_approved; the port does."""
        sent = []

        class Recorder:
            def signal(self, work_type):
                sent.append(work_type)

        db.signals = Recorder()
        event_id = factory.event(user, review_status="active")
        cw.enqueue_calendar_work(db, user, event_id, "upsert", {"title": "t"})
        assert sent == ["event_approved"]

        sent.clear()
        with pytest.raises(InvalidArgument):
            cw.enqueue_calendar_work(db, user, event_id, "upsert", None)
        with pytest.raises(NotNullViolation):  # rolled back: nothing announced
            cw.enqueue_calendar_work(db, user, event_id, None)
        assert sent == []

    def test_live_hint_names_the_owner(self, db, factory, user):
        published = []

        class Bus:
            def publish(self, topic, message):
                published.append((topic, message["resource"]))

        db.bus = Bus()
        event_id = factory.event(user, review_status="active")
        cw.enqueue_calendar_work(db, user, event_id, "cancel")
        assert (f"user:{user}", "calendar_work_items") in published

    def test_owner_check_trigger(self, db, factory, user):
        other = factory.user()
        event_id = factory.event(other)
        with (
            pytest.raises(InvariantViolation, match="calendar work item owner does not match event owner"),
            db.write() as tx,
        ):
            tx.execute(
                "INSERT INTO calendar_work_items (id, event_id, user_id, action, generation) "
                "VALUES ('00000000-0000-0000-0000-0000000000b1', ?, ?, 'cancel', 1)",
                (event_id, user),
            )


# ---------------------------------------------------------------------------
# claim
# ---------------------------------------------------------------------------


class TestClaim:
    def test_enqueue_claim_complete_is_item_fenced(self, db, factory, user):
        event_id = factory.event(user, review_status="active", title="S2 event")
        queued = cw.enqueue_calendar_work(db, user, event_id, "upsert", _desired())
        claimed = _claim(db, "s2-worker")
        assert claimed is not None
        item, event = claimed
        assert item["id"] == queued["id"]
        assert item["status"] == "processing"
        assert event["id"] == event_id
        assert cw.complete_calendar_work(db, item["id"], "s2-worker", item["generation"], "google-s2-event") is True
        final = _event(db, event_id)
        assert (final["review_status"], final["google_calendar_event_id"]) == ("active", "google-s2-event")
        assert final["synced_at"] is not None
        done = _item(db, item["id"])
        assert done["status"] == "succeeded"
        assert done["provider_event_id"] == "google-s2-event"
        assert (done["locked_by"], done["locked_until"]) == (None, None)
        assert done["completed_at"] is not None

    def test_claim_sets_the_lease(self, db, factory, user):
        event_id = _approved(db, factory, user)
        before = _event(db, event_id)["updated_at"]
        item, event = _claim(db, "test-worker-1", 120)
        assert item["attempts"] == 1
        assert item["locked_by"] == "test-worker-1"
        assert item["provider"] == "google_calendar"
        assert item["action"] == "upsert"
        lease = parse_timestamp(item["locked_until"]) - parse_timestamp(item["updated_at"])
        assert lease == timedelta(seconds=120)
        assert event["updated_at"] > before
        assert _items_for(db, event_id)[0]["status"] == "processing"

    @pytest.mark.parametrize("lease_seconds", [0, -5])
    def test_lease_is_at_least_one_second(self, db, factory, user, lease_seconds):
        _approved(db, factory, user)
        item, _ = _claim(db, "w", lease_seconds)
        lease = parse_timestamp(item["locked_until"]) - parse_timestamp(item["updated_at"])
        assert lease == timedelta(seconds=1)

    def test_nothing_to_claim(self, db):
        assert _claim(db) is None

    def test_second_claim_gets_nothing(self, db, factory, user):
        _approved(db, factory, user)
        assert _claim(db, "worker-1") is not None
        assert _claim(db, "worker-2") is None

    def test_oldest_first_and_every_worker_gets_a_different_event(self, db, factory, user):
        event_ids = [_approved(db, factory, user, title=f"Event {i}") for i in range(3)]
        claimed = [_claim(db, f"worker-{i}")[1]["id"] for i in range(3)]
        assert claimed == event_ids

    def test_concurrent_claims_never_share_an_item(self, db, factory, user):
        event_ids = {_approved(db, factory, user, title=f"E{i}") for i in range(30)}
        claimed: list[str] = []
        lock = threading.Lock()
        barrier = threading.Barrier(6)

        def work(n):
            barrier.wait()
            while True:
                got = _claim(db, f"thread-{n}")
                if got is None:
                    return
                with lock:
                    claimed.append(got[0]["id"])

        threads = [threading.Thread(target=work, args=(n,)) for n in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(claimed) == 30
        assert len(set(claimed)) == 30
        assert {_item(db, i)["event_id"] for i in claimed} == event_ids

    def test_excludes_users_without_an_active_calendar_integration(self, db, factory, user):
        with db.write() as tx:
            tx.execute("UPDATE integrations SET status = 'expired' WHERE user_id = ?", (user,))
        _approved(db, factory, user)
        assert _claim(db) is None

    def test_a_user_without_any_integration_is_not_claimed(self, db, factory):
        lonely = factory.user()
        _approved(db, factory, lonely)
        assert _claim(db) is None

    def test_respects_next_retry_at_and_the_attempt_budget(self, db, factory, user):
        event_id = _approved(db, factory, user)
        item_id = _items_for(db, event_id)[0]["id"]
        _set(db, "calendar_work_items", item_id, next_retry_at=to_timestamp(utc_now() + timedelta(hours=1)))
        assert _claim(db) is None
        _set(db, "calendar_work_items", item_id, next_retry_at=to_timestamp(utc_now() - timedelta(seconds=1)))
        assert _claim(db)[0]["id"] == item_id

        other = _approved(db, factory, user)
        other_item = _items_for(db, other)[0]["id"]
        _set(db, "calendar_work_items", other_item, attempts=3)
        assert _claim(db) is None

    def test_expired_processing_item_is_reclaimable(self, db, factory, user):
        event_id = _approved(db, factory, user)
        item, _ = _claim(db, "crashed-worker", 1)
        _set(db, "calendar_work_items", item["id"], locked_until=to_timestamp(utc_now() - timedelta(seconds=1)))
        reclaimed, _ = _claim(db, "reclaimer", 60)
        assert reclaimed["id"] == item["id"]
        assert reclaimed["event_id"] == event_id
        assert reclaimed["locked_by"] == "reclaimer"
        assert reclaimed["attempts"] == 2
        # The crashed worker's lease is dead.
        assert cw.complete_calendar_work(db, item["id"], "crashed-worker", item["generation"], "g") is False

    def test_an_unexpired_lease_is_not_reclaimed(self, db, factory, user):
        _approved(db, factory, user)
        _claim(db, "alive", 300)
        assert _claim(db, "thief") is None

    def test_an_expired_lease_with_no_budget_left_is_not_reclaimed(self, db, factory, user):
        _approved(db, factory, user)
        item, _ = _claim(db, "crashed", 1)
        _set(db, "calendar_work_items", item["id"], attempts=3,
             locked_until=to_timestamp(utc_now() - timedelta(seconds=1)))
        assert _claim(db) is None

    def test_pending_work_is_claimed_before_expired_leases(self, db, factory, user):
        expired_event = _approved(db, factory, user)
        expired, _ = _claim(db, "crashed", 1)
        _set(db, "calendar_work_items", expired["id"], locked_until=to_timestamp(utc_now() - timedelta(hours=1)))
        fresh_event = _approved(db, factory, user)
        assert _claim(db, "w1")[1]["id"] == fresh_event
        assert _claim(db, "w2")[1]["id"] == expired_event

    def test_expired_leases_are_reclaimed_oldest_lease_first(self, db, factory, user):
        a = _approved(db, factory, user)
        b = _approved(db, factory, user)
        ia, _ = _claim(db, "x")
        ib, _ = _claim(db, "y")
        _set(db, "calendar_work_items", ia["id"], locked_until=to_timestamp(utc_now() - timedelta(seconds=10)))
        _set(db, "calendar_work_items", ib["id"], locked_until=to_timestamp(utc_now() - timedelta(seconds=20)))
        assert _claim(db, "r1")[1]["id"] == b
        assert _claim(db, "r2")[1]["id"] == a

    def test_unwritable_items_never_starve_the_queue(self, db, factory, user):
        """Postgres scanned the whole queue; the batched port must too."""
        blocked_user = factory.user()
        factory.integration(blocked_user, provider="google_calendar", status="expired")
        for i in range(cw.CLAIM_SCAN * 2 + 5):
            _approved(db, factory, blocked_user, title=f"blocked {i}")
        writable = _approved(db, factory, user)
        assert _claim(db)[1]["id"] == writable
        assert _claim(db) is None


# ---------------------------------------------------------------------------
# routing per provider (test_integration_outlook_calendar.py)
# ---------------------------------------------------------------------------


class TestClaimRoutesByProvider:
    def test_an_outlook_only_user_is_claimed_and_stamped_outlook(self, db, factory):
        user = factory.user()
        factory.integration(user, provider="outlook", scopes=OUTLOOK_CALENDAR_SCOPES)
        _approved(db, factory, user)
        item, _ = _claim(db)
        assert item["provider"] == "outlook"

    def test_a_mail_only_outlook_grant_is_never_claimed(self, db, factory):
        user = factory.user()
        factory.integration(user, provider="outlook", scopes=OUTLOOK_MAIL_ONLY)
        event_id = _approved(db, factory, user)
        assert _claim(db) is None
        item = _items_for(db, event_id)[0]
        assert (item["status"], item["provider"]) == ("pending", None)
        # Granting the calendar makes the very same item claimable.
        _set_scopes(db, user, "outlook", OUTLOOK_CALENDAR_SCOPES)
        assert _claim(db)[1]["id"] == event_id

    def test_scope_match_is_case_insensitive_suffix(self, db, factory):
        user = factory.user()
        factory.integration(user, provider="outlook", scopes=["https://graph.microsoft.com/calendars.readwrite"])
        _approved(db, factory, user)
        assert _claim(db)[0]["provider"] == "outlook"

    def test_the_target_calendar_chooses_the_provider(self, db, factory):
        user = factory.user()
        factory.integration(user, provider="google_calendar", scopes=["calendar"])
        factory.integration(user, provider="outlook", scopes=OUTLOOK_CALENDAR_SCOPES)
        _target(db, user, "outlook:AAMkCAL")
        _approved(db, factory, user)
        assert _claim(db)[0]["provider"] == "outlook"

    def test_an_empty_target_is_unset(self, db, factory):
        user = factory.user()
        factory.integration(user, provider="google_calendar")
        factory.integration(user, provider="outlook", scopes=OUTLOOK_CALENDAR_SCOPES)
        _target(db, user, "")
        _approved(db, factory, user)
        assert _claim(db)[0]["provider"] == "google_calendar"

    def test_a_target_whose_provider_is_not_writable_is_not_claimed(self, db, factory):
        user = factory.user()
        factory.integration(user, provider="google_calendar")
        _target(db, user, "outlook:AAMkCAL")
        _approved(db, factory, user)
        assert _claim(db) is None

    def test_an_event_already_in_google_stays_in_google(self, db, factory):
        user = factory.user()
        factory.integration(user, provider="google_calendar", scopes=["calendar"])
        factory.integration(user, provider="outlook", scopes=OUTLOOK_CALENDAR_SCOPES)
        _target(db, user, "outlook:AAMkCAL")
        _approved(db, factory, user, google_calendar_event_id="googleid123")
        assert _claim(db)[0]["provider"] == "google_calendar"

    def test_an_event_already_in_outlook_stays_in_outlook(self, db, factory):
        user = factory.user()
        factory.integration(user, provider="google_calendar")
        factory.integration(user, provider="outlook", scopes=OUTLOOK_CALENDAR_SCOPES)
        _approved(db, factory, user, google_calendar_event_id="outlook:E1")
        assert _claim(db)[0]["provider"] == "outlook"

    def test_an_open_circuit_excludes_only_its_provider(self, db, factory):
        user = factory.user()
        factory.integration(user, provider="outlook", scopes=OUTLOOK_CALENDAR_SCOPES)
        _approved(db, factory, user)
        assert _claim(db, providers=["google_calendar"]) is None
        assert _claim(db, providers=[]) is None
        assert _claim(db, providers=["outlook"]) is not None

    def test_a_stamped_provider_is_kept_on_reclaim(self, db, factory):
        user = factory.user()
        factory.integration(user, provider="google_calendar")
        factory.integration(user, provider="outlook", scopes=OUTLOOK_CALENDAR_SCOPES)
        _approved(db, factory, user)
        item, _ = _claim(db, "crashed", 1)
        assert item["provider"] == "google_calendar"
        _target(db, user, "outlook:AAMkCAL")
        _set(db, "calendar_work_items", item["id"], locked_until=to_timestamp(utc_now() - timedelta(seconds=1)))
        assert _claim(db, providers=["outlook"]) is None
        assert _claim(db, providers=["google_calendar"])[0]["provider"] == "google_calendar"

    def test_routing_helpers(self, db, factory):
        user = factory.user()
        event_id = factory.event(user)
        assert cw.calendar_write_provider(db, user, event_id) == "google_calendar"  # nothing connected
        factory.integration(user, provider="outlook", scopes=OUTLOOK_MAIL_ONLY)
        assert cw.calendar_write_provider(db, user, event_id) == "google_calendar"
        _set_scopes(db, user, "outlook", OUTLOOK_CALENDAR_SCOPES)
        assert cw.calendar_write_provider(db, user, event_id) == "outlook"
        factory.integration(user, provider="google_calendar")
        assert cw.calendar_write_provider(db, user, event_id) == "google_calendar"
        _target(db, user, "outlook:CAL")
        assert cw.calendar_write_provider(db, user, event_id) == "outlook"
        _set(db, "events", event_id, google_calendar_event_id="g-1")
        assert cw.calendar_write_provider(db, user, event_id) == "google_calendar"
        # Any non-NULL id decides, even '' (Postgres: IS NOT NULL).
        assert cw.write_provider_for("", "outlook:CAL", []) == "google_calendar"
        assert cw.write_provider_for("Outlook:X", None, []) == "google_calendar"  # LIKE is case-sensitive


# ---------------------------------------------------------------------------
# complete / fail / defer
# ---------------------------------------------------------------------------


class TestFencedTransitions:
    def test_stale_completion_after_supersede_is_fenced(self, db, factory, user):
        event_id = factory.event(user, review_status="pending_review", title="Race")
        first = cw.enqueue_calendar_work(db, user, event_id, "upsert", _desired("first"))
        item, _ = _claim(db, "old-worker")
        assert item["id"] == first["id"]
        second = cw.enqueue_calendar_work(db, user, event_id, "cancel")
        assert first["id"] != second["id"]
        assert cw.complete_calendar_work(db, *_lease(item), "stale-google-event") is False
        row = _item(db, second["id"])
        assert (row["status"], row["action"], row["generation"]) == ("pending", "cancel", 2)
        assert _event(db, event_id)["google_calendar_event_id"] is None

    def test_wrong_worker_or_generation_is_fenced_everywhere(self, db, factory, user):
        _approved(db, factory, user)
        item, _ = _claim(db, "w")
        item_id, _, generation = _lease(item)
        assert cw.complete_calendar_work(db, item_id, "other", generation, "g") is False
        assert cw.complete_calendar_work(db, item_id, "w", generation + 1, "g") is False
        assert cw.complete_calendar_work(db, item_id, "w", None, "g") is False
        assert cw.fail_calendar_work(db, item_id, "other", generation, "x") == {"fenced": True}
        assert cw.defer_calendar_work(db, item_id, "w", generation + 1, "2026-01-01T00:00:00Z") is False
        missing = "00000000-0000-0000-0000-00000000beef"
        assert cw.complete_calendar_work(db, missing, "w", 1, "g") is False
        assert cw.fail_calendar_work(db, missing, "w", 1, "x") == {"fenced": True}
        assert cw.defer_calendar_work(db, missing, "w", 1, "2026-01-01T00:00:00Z") is False
        assert _item(db, item_id)["status"] == "processing"
        assert cw.complete_calendar_work(db, item_id, "w", generation, "g") is True
        assert cw.complete_calendar_work(db, item_id, "w", generation, "g") is False  # not processing

    def test_complete_without_an_id_keeps_the_existing_one(self, db, factory, user):
        event_id = _approved(db, factory, user, google_calendar_event_id="g-existing")
        item, _ = _claim(db, "w")
        assert cw.complete_calendar_work(db, *_lease(item), None, "rev-9") is True
        assert _event(db, event_id)["google_calendar_event_id"] == "g-existing"
        done = _item(db, item["id"])
        assert done["provider_event_id"] == "g-existing"
        assert done["expected_provider_revision"] == "rev-9"

    def test_fail_with_retry(self, db, factory, user):
        event_id = _approved(db, factory, user)
        item, _ = _claim(db, "worker-1")
        before = _event(db, event_id)["updated_at"]
        result = cw.fail_calendar_work(db, *_lease(item), "calendar_sync_failed", "Test sync error", True)
        assert result == {"fenced": False, "status": "pending"}
        row = _item(db, item["id"])
        assert row["status"] == "pending"
        assert row["failure_code"] == "calendar_sync_failed"
        assert row["failure_detail"] == "Test sync error"
        assert (row["locked_by"], row["locked_until"]) == (None, None)
        assert row["completed_at"] is None
        delay = parse_timestamp(row["next_retry_at"]) - parse_timestamp(row["updated_at"])
        assert delay == timedelta(seconds=60)  # attempts = 1
        assert _event(db, event_id)["review_status"] == "active"
        assert _event(db, event_id)["updated_at"] > before
        assert _claim(db) is None  # backing off

    def test_exhausted_budget_fails_terminally(self, db, factory, user):
        _approved(db, factory, user)
        item, _ = _claim(db, "w")
        _set(db, "calendar_work_items", item["id"], attempts=3)
        assert cw.fail_calendar_work(db, *_lease(item), "calendar_sync_failed", "down") == {
            "fenced": False, "status": "failed",
        }
        row = _item(db, item["id"])
        assert row["status"] == "failed"
        assert row["completed_at"] is not None
        assert row["next_retry_at"] is None
        assert row["locked_by"] is None

    def test_not_retryable_parks_as_blocked_without_backoff(self, db, factory, user):
        _approved(db, factory, user)
        item, _ = _claim(db, "w")
        result = cw.fail_calendar_work(
            db, *_lease(item), "oauth_required", "Google Calendar needs to be reconnected.", False
        )
        assert result == {"fenced": False, "status": "blocked"}
        row = _item(db, item["id"])
        assert (row["status"], row["failure_code"]) == ("blocked", "oauth_required")
        assert row["next_retry_at"] is None
        assert row["attempts"] == 1

    def test_failure_text_is_truncated(self, db, factory, user):
        _approved(db, factory, user)
        item, _ = _claim(db, "w")
        cw.fail_calendar_work(db, *_lease(item), "c" * 150, "d" * 900)
        row = _item(db, item["id"])
        assert (len(row["failure_code"]), len(row["failure_detail"])) == (100, 500)

    @pytest.mark.parametrize(
        ("attempts", "delay"),
        [(0, 60), (1, 60), (2, 120), (3, 240), (4, 480), (5, 960), (6, 1800), (7, 1800), (40, 1800)],
    )
    def test_backoff_matches_postgres(self, attempts, delay):
        assert cw.retry_delay_seconds(attempts) == delay

    def test_defer_releases_without_spending_an_attempt(self, db, factory, user):
        event_id = _approved(db, factory, user)
        item, _ = _claim(db, "worker-1")
        assert item["attempts"] == 1
        reset_at = "2026-04-10T00:00:00+00:00"
        assert cw.defer_calendar_work(db, *_lease(item), reset_at, "Daily calendar sync quota exceeded") is True
        row = _item(db, item["id"])
        assert row["status"] == "pending"
        assert row["attempts"] == 0
        assert row["failure_code"] == "calendar_quota"
        assert row["failure_detail"] == "Daily calendar sync quota exceeded"
        assert row["next_retry_at"] == "2026-04-10T00:00:00.000000Z"
        assert (row["locked_by"], row["locked_until"]) == (None, None)
        assert _event(db, event_id)["review_status"] == "active"

    def test_defer_never_takes_attempts_below_zero_and_reads_naive_time_as_utc(self, db, factory, user):
        _approved(db, factory, user)
        item, _ = _claim(db, "w")
        _set(db, "calendar_work_items", item["id"], attempts=0)
        assert cw.defer_calendar_work(db, *_lease(item), "2026-04-10T08:30:00") is True
        row = _item(db, item["id"])
        assert row["attempts"] == 0
        assert row["next_retry_at"] == "2026-04-10T08:30:00.000000Z"
        assert row["failure_detail"] == "calendar quota exceeded"


# ---------------------------------------------------------------------------
# cancellation, unsync, undo
# ---------------------------------------------------------------------------


class TestCancellation:
    def test_cancel_claim_and_completion_are_worker_owned(self, db, factory, user):
        event_id = factory.event(
            user, title="Original title", review_status="active", google_calendar_event_id="google-c3-event"
        )
        queued = cw.queue_event_cancellation(db, user, event_id)
        assert queued["status"] == "cancel_queued"
        assert queued["already_cancelled"] is False
        row = _item(db, queued["work_item_id"])
        assert (row["status"], row["action"], row["generation"]) == ("pending", "cancel", 1)
        assert row["provider_event_id"] == "google-c3-event"

        item, event = _claim(db, "c3-worker")
        assert event["id"] == event_id
        assert item["action"] == "cancel"
        assert _item(db, queued["work_item_id"])["status"] == "processing"
        # complete_event_cancellation passes the item's own provider_event_id.
        assert cw.complete_calendar_work(db, *_lease(item), item["provider_event_id"]) is True
        final = _event(db, event_id)
        assert (final["review_status"], final["title"], final["google_calendar_event_id"]) == (
            "cancelled", "Original title", None,
        )
        assert final["synced_at"] is None

    def test_a_pending_review_event_becomes_active_then_cancelled(self, db, factory, user):
        event_id = factory.event(user, review_status="pending_review")
        cw.queue_event_cancellation(db, user, event_id)
        assert _event(db, event_id)["review_status"] == "active"
        item, _ = _claim(db)
        cw.complete_calendar_work(db, *_lease(item), None)
        assert _event(db, event_id)["review_status"] == "cancelled"

    def test_already_cancelled(self, db, factory, user):
        event_id = factory.event(user, review_status="cancelled")
        assert cw.queue_event_cancellation(db, user, event_id) == {
            "event_id": event_id, "status": "cancelled", "already_cancelled": True,
        }
        assert _items_for(db, event_id) == []

    def test_rejected_or_syncing_events_cannot_be_cancelled(self, db, factory, user):
        rejected = factory.event(user, review_status="rejected")
        with pytest.raises(InvalidArgument, match="cannot be cancelled in its current state"):
            cw.queue_event_cancellation(db, user, rejected)
        syncing = _approved(db, factory, user)
        _claim(db)
        with pytest.raises(InvalidArgument, match="cannot be cancelled in its current state"):
            cw.queue_event_cancellation(db, user, syncing)
        with pytest.raises(NotOwned):
            cw.queue_event_cancellation(db, factory.user(), syncing)

    def test_stale_upsert_completion_cannot_reset_cancellation(self, db, factory, user):
        event_id = factory.event(user, review_status="active", google_calendar_event_id="google-race-event")
        cw.enqueue_calendar_work(db, user, event_id, "upsert", {"title": "Race event"})
        old, _ = _claim(db, "upsert-worker")
        cw.enqueue_calendar_work(db, user, event_id, "cancel")
        assert cw.complete_calendar_work(db, *_lease(old), "google-race-event") is False
        assert _event(db, event_id)["review_status"] == "active"
        latest = _items_for(db, event_id)[-1]
        assert (latest["status"], latest["action"]) == ("pending", "cancel")




class TestUndo:
    def test_undo_with_calendar_work(self, db, factory, user):
        event_id = factory.event(user, review_status="active", google_calendar_event_id="g-1")
        result = cw.undo_event_and_enqueue_calendar_work(
            db, user, event_id, "cancel", {"delete_remote": True}
        )
        assert result["status"] == "pending_review"
        assert result["generation"] == 1
        assert _item(db, result["work_item_id"])["desired_event"] == {"delete_remote": True}
        assert _event(db, event_id)["review_status"] == "pending_review"

    def test_undo_without_calendar_work(self, db, factory, user):
        event_id = factory.event(user, review_status="active")
        assert cw.undo_event_and_enqueue_calendar_work(db, user, event_id) == {
            "status": "pending_review", "work_item_id": None, "generation": None,
        }
        assert _items_for(db, event_id) == []
        assert _event(db, event_id)["review_status"] == "pending_review"

    def test_undo_not_owned(self, db, factory, user):
        event_id = factory.event(user, review_status="active")
        with pytest.raises(NotOwned):
            cw.undo_event_and_enqueue_calendar_work(db, factory.user(), event_id)
        assert _event(db, event_id)["review_status"] == "active"


# ---------------------------------------------------------------------------
# reads and the sync log
# ---------------------------------------------------------------------------


class TestReads:
    def test_get_leased_item(self, db, factory, user):
        _approved(db, factory, user)
        item, _ = _claim(db, "w")
        assert cw.get_leased_item(db, *_lease(item))["id"] == item["id"]
        assert cw.get_leased_item(db, item["id"], "other", item["generation"]) is None
        assert cw.get_leased_item(db, item["id"], "w", item["generation"] + 1) is None
        cw.complete_calendar_work(db, *_lease(item), "g")
        assert cw.get_leased_item(db, *_lease(item)) is None



    def test_sync_log_latest_snapshot(self, db, factory, user):
        event_id = factory.event(user, review_status="active")
        assert cw.latest_sync_snapshot(db, user, event_id) is None
        cw.log_calendar_sync(db, user, event_id, "g-1", "created", {"summary": "first"})
        cw.log_calendar_sync(db, user, event_id, "g-1", "updated", {"summary": "second"})
        cw.log_calendar_sync(db, user, event_id, "g-1", "deleted", {"summary": "gone"})
        assert cw.latest_sync_snapshot(db, user, event_id) == {"summary": "second"}
        assert cw.latest_sync_snapshot(db, user, event_id, ["deleted"]) == {"summary": "gone"}
        assert cw.latest_sync_snapshot(db, factory.user(), event_id) is None
        cw.log_calendar_sync(db, user, event_id, "g-1", "updated", ["not", "an", "object"])
        assert cw.latest_sync_snapshot(db, user, event_id) is None

    def test_sync_log_refuses_bad_rows(self, db, factory, user):
        from selko.db.errors import CheckViolation

        event_id = factory.event(user)
        with pytest.raises(CheckViolation):
            cw.log_calendar_sync(db, user, event_id, "g-1", "moved", {})
        with pytest.raises(NotNullViolation):  # snapshot_synced is NOT NULL, as in Postgres
            cw.log_calendar_sync(db, user, event_id, "g-1", "created", None)
