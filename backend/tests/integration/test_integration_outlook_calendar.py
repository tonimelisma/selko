"""Calendar routing with Google and Outlook side by side, on a real SQLite database.

Ported from the migration 20261031000001 tests: the claim, recovery and
reauthorization (`selko.db.calendar_work`, `selko.db.recovery`) and the
worker's recovery wrapper (`services.calendars`), with Google and Outlook
integrations side by side.
"""

import pytest

from selko.db import calendar_work
from selko.db import integrations as db_integrations
from selko.db import recovery as db_recovery
from selko.services.calendars import requeue_calendar_recovery_batch

OUTLOOK_CALENDAR_SCOPES = ["Mail.Read", "User.Read", "Calendars.ReadWrite"]


@pytest.fixture
def user_id(factory):
    return factory.user()


def _connect(db, user_id, provider, scopes):
    db_recovery.complete_integration_reauthorization(
        db,
        user_id,
        provider,
        access_token="access",
        refresh_token="refresh",
        token_expiry=None,
        scopes=scopes,
        provider_email=None,
    )


def _approved_event(db, factory, user_id, google_calendar_event_id=None):
    event_id = factory.event(
        user_id,
        review_status="active",
        title="Outlook calendar test event",
        start_datetime="2026-11-05T14:00:00.000000Z",
        google_calendar_event_id=google_calendar_event_id,
    )
    calendar_work.enqueue_calendar_work(
        db, user_id, event_id, "upsert", {"title": "Outlook calendar test event"}
    )
    return event_id


def _target(db, user_id, calendar_id):
    db_integrations.upsert_calendar_settings(db, user_id, {"target_calendar_id": calendar_id})


def _claim(db, providers=None):
    claimed = calendar_work.claim_calendar_work_item(db, "outlook-it", 60, providers=providers)
    return None if claimed is None else claimed[0]


@pytest.mark.integration
class TestClaimRoutesByProvider:
    async def test_an_outlook_only_user_is_claimed_and_stamped_outlook(self, db, factory, user_id):
        _connect(db, user_id, "outlook", OUTLOOK_CALENDAR_SCOPES)
        _approved_event(db, factory, user_id)

        claimed = _claim(db)

        assert claimed is not None
        assert claimed["provider"] == "outlook"

    async def test_a_mail_only_outlook_grant_is_never_claimed(self, db, factory, user_id):
        """Claiming it would only fail on Graph; it waits for the reconnect."""
        _connect(db, user_id, "outlook", ["Mail.Read", "User.Read"])
        event_id = _approved_event(db, factory, user_id)

        assert _claim(db) is None
        item = db.query_one(
            "SELECT status, provider FROM calendar_work_items WHERE event_id = ?", (event_id,))
        assert (item["status"], item["provider"]) == ("pending", None)

        # Granting the calendar makes the very same item claimable.
        _connect(db, user_id, "outlook", OUTLOOK_CALENDAR_SCOPES)
        claimed = _claim(db)
        assert claimed is not None and claimed["event_id"] == event_id

    async def test_the_target_calendar_chooses_the_provider(self, db, factory, user_id):
        _connect(db, user_id, "google_calendar", ["calendar"])
        _connect(db, user_id, "outlook", OUTLOOK_CALENDAR_SCOPES)
        _target(db, user_id, "outlook:AAMkCAL")
        _approved_event(db, factory, user_id)

        assert _claim(db)["provider"] == "outlook"

    async def test_an_event_already_in_google_stays_in_google(self, db, factory, user_id):
        _connect(db, user_id, "google_calendar", ["calendar"])
        _connect(db, user_id, "outlook", OUTLOOK_CALENDAR_SCOPES)
        _target(db, user_id, "outlook:AAMkCAL")
        _approved_event(db, factory, user_id, google_calendar_event_id="googleid123")

        assert _claim(db)["provider"] == "google_calendar"

    async def test_an_open_circuit_excludes_only_its_provider(self, db, factory, user_id):
        _connect(db, user_id, "outlook", OUTLOOK_CALENDAR_SCOPES)
        _approved_event(db, factory, user_id)

        assert _claim(db, providers=["google_calendar"]) is None
        assert _claim(db, providers=["outlook"]) is not None


@pytest.mark.integration
class TestRecoveryPerProvider:
    async def test_a_mail_only_outlook_consent_opens_no_recovery(self, db, user_id):
        _connect(db, user_id, "outlook", ["Mail.Read", "User.Read"])
        rows = db.query("SELECT id FROM integration_recoveries WHERE user_id = ?", (user_id,))
        assert rows == []

    async def test_an_outlook_calendar_consent_opens_a_recovery(self, db, user_id):
        _connect(db, user_id, "outlook", OUTLOOK_CALENDAR_SCOPES)
        rows = db.query(
            "SELECT provider, status FROM integration_recoveries WHERE user_id = ?", (user_id,))
        assert [tuple(r) for r in rows] == [("outlook", "pending")]

    async def test_reconnecting_requeues_parked_items_for_that_provider_only(self, db, factory, user_id):
        """The recovery used to tag parked items and leave them parked forever."""
        _connect(db, user_id, "google_calendar", ["calendar"])
        _connect(db, user_id, "outlook", OUTLOOK_CALENDAR_SCOPES)
        with db.write() as tx:
            tx.execute("DELETE FROM integration_recoveries WHERE user_id = ?", (user_id,))

        outlook_event = _approved_event(db, factory, user_id, google_calendar_event_id="outlook:E1")
        google_event = _approved_event(db, factory, user_id, google_calendar_event_id="googleid1")
        with db.write() as tx:
            tx.execute(
                "UPDATE calendar_work_items SET status = 'blocked', failure_code = 'oauth_required', "
                "attempts = 3 WHERE event_id IN (?, ?)",
                (outlook_event, google_event),
            )

        _connect(db, user_id, "outlook", OUTLOOK_CALENDAR_SCOPES)
        recovery = db_recovery.claim_integration_recovery(db, "outlook-it", lock_seconds=120)
        assert recovery is not None and recovery["provider"] == "outlook"

        requeued = await requeue_calendar_recovery_batch(db, recovery["id"], "outlook-it")
        assert requeued == 1

        items = {
            row["event_id"]: row
            for row in db.query(
                "SELECT event_id, status, attempts, max_attempts FROM calendar_work_items "
                "WHERE event_id IN (?, ?)",
                (outlook_event, google_event),
            )
        }
        assert items[outlook_event]["status"] == "pending"
        assert items[outlook_event]["attempts"] < items[outlook_event]["max_attempts"]
        assert items[google_event]["status"] == "blocked"

        claimed = _claim(db)
        assert claimed is not None and claimed["event_id"] == outlook_event
