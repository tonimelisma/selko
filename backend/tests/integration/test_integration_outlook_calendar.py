"""Migration 20261031000001 against a real database.

SQL that has never been executed has not been tested: these call the claim,
recovery and reauthorization functions the migration redefines, with Google
and Outlook integrations side by side.
"""

import pytest

from selko.services.calendars import requeue_calendar_recovery_batch
from selko.services.events import claim_approved_event_for_sync
from selko.services.integrations import (
    claim_integration_recovery,
    complete_integration_reauthorization,
)

OUTLOOK_CALENDAR_SCOPES = ["Mail.Read", "User.Read", "Calendars.ReadWrite"]


@pytest.fixture
def user_id(isolated_user):
    return isolated_user["id"]


@pytest.fixture(autouse=True)
def _cleanup(admin_client, user_id):
    def clear():
        admin_client.table("events").delete().eq("user_id", user_id).execute()
        admin_client.table("integration_recoveries").delete().eq("user_id", user_id).execute()
        admin_client.table("user_calendar_settings").delete().eq("user_id", user_id).execute()
        admin_client.table("integrations").delete().eq("user_id", user_id).in_(
            "provider", ["google_calendar", "outlook"]
        ).execute()

    clear()
    yield
    clear()


def _connect(admin_client, user_id, provider, scopes):
    complete_integration_reauthorization(
        admin_client,
        user_id=user_id,
        provider=provider,
        access_token="access",
        refresh_token="refresh",
        token_expiry=None,
        scopes=scopes,
        provider_email=None,
    )


def _approved_event(admin_client, user_id, google_calendar_event_id=None):
    event = admin_client.table("events").insert({
        "user_id": user_id,
        "title": "Outlook calendar test event",
        "start_datetime": "2026-11-05T14:00:00Z",
        "review_status": "active",
        "google_calendar_event_id": google_calendar_event_id,
    }).execute().data[0]
    admin_client.rpc("enqueue_calendar_work", {
        "p_event_id": event["id"],
        "p_user_id": user_id,
        "p_action": "upsert",
        "p_desired_event": {"title": event["title"]},
    }).execute()
    return event["id"]


def _target(admin_client, user_id, calendar_id):
    admin_client.table("user_calendar_settings").upsert({
        "user_id": user_id, "target_calendar_id": calendar_id,
    }).execute()


async def _claim_for(pg_pool, user_id, providers=None):
    """Claim until this user's item comes up; other suites may leave work."""
    for _ in range(50):
        event = await claim_approved_event_for_sync(pg_pool, "outlook-it", 60, providers=providers)
        if event is None:
            return None
        if str(event["user_id"]) == str(user_id):
            return event
    return None


@pytest.mark.integration
@pytest.mark.development
class TestClaimRoutesByProvider:
    async def test_an_outlook_only_user_is_claimed_and_stamped_outlook(self, admin_client, user_id, pg_pool):
        _connect(admin_client, user_id, "outlook", OUTLOOK_CALENDAR_SCOPES)
        _approved_event(admin_client, user_id)

        claimed = await _claim_for(pg_pool, user_id)

        assert claimed is not None
        assert claimed["calendar_work_item_provider"] == "outlook"

    async def test_a_mail_only_outlook_grant_is_never_claimed(self, admin_client, user_id, pg_pool):
        """Claiming it would only fail on Graph; it waits for the reconnect."""
        _connect(admin_client, user_id, "outlook", ["Mail.Read", "User.Read"])
        event_id = _approved_event(admin_client, user_id)

        assert await _claim_for(pg_pool, user_id) is None
        item = admin_client.table("calendar_work_items").select("status,provider").eq(
            "event_id", event_id
        ).single().execute().data
        assert item == {"status": "pending", "provider": None}

        # Granting the calendar makes the very same item claimable.
        _connect(admin_client, user_id, "outlook", OUTLOOK_CALENDAR_SCOPES)
        claimed = await _claim_for(pg_pool, user_id)
        assert claimed is not None and claimed["id"] == event_id

    async def test_the_target_calendar_chooses_the_provider(self, admin_client, user_id, pg_pool):
        _connect(admin_client, user_id, "google_calendar", ["calendar"])
        _connect(admin_client, user_id, "outlook", OUTLOOK_CALENDAR_SCOPES)
        _target(admin_client, user_id, "outlook:AAMkCAL")
        _approved_event(admin_client, user_id)

        claimed = await _claim_for(pg_pool, user_id)

        assert claimed["calendar_work_item_provider"] == "outlook"

    async def test_an_event_already_in_google_stays_in_google(self, admin_client, user_id, pg_pool):
        _connect(admin_client, user_id, "google_calendar", ["calendar"])
        _connect(admin_client, user_id, "outlook", OUTLOOK_CALENDAR_SCOPES)
        _target(admin_client, user_id, "outlook:AAMkCAL")
        _approved_event(admin_client, user_id, google_calendar_event_id="googleid123")

        claimed = await _claim_for(pg_pool, user_id)

        assert claimed["calendar_work_item_provider"] == "google_calendar"

    async def test_an_open_circuit_excludes_only_its_provider(self, admin_client, user_id, pg_pool):
        _connect(admin_client, user_id, "outlook", OUTLOOK_CALENDAR_SCOPES)
        _approved_event(admin_client, user_id)

        assert await _claim_for(pg_pool, user_id, providers=["google_calendar"]) is None
        assert await _claim_for(pg_pool, user_id, providers=["outlook"]) is not None


@pytest.mark.integration
@pytest.mark.development
class TestRecoveryPerProvider:
    async def test_a_mail_only_outlook_consent_opens_no_recovery(self, admin_client, user_id):
        _connect(admin_client, user_id, "outlook", ["Mail.Read", "User.Read"])
        rows = admin_client.table("integration_recoveries").select("id").eq("user_id", user_id).execute().data
        assert rows == []

    async def test_an_outlook_calendar_consent_opens_a_recovery(self, admin_client, user_id):
        _connect(admin_client, user_id, "outlook", OUTLOOK_CALENDAR_SCOPES)
        rows = admin_client.table("integration_recoveries").select("provider,status").eq(
            "user_id", user_id
        ).execute().data
        assert rows == [{"provider": "outlook", "status": "pending"}]

    async def test_reconnecting_requeues_parked_items_for_that_provider_only(
        self, admin_client, user_id, pg_pool
    ):
        """The recovery used to tag parked items and leave them parked forever."""
        _connect(admin_client, user_id, "google_calendar", ["calendar"])
        _connect(admin_client, user_id, "outlook", OUTLOOK_CALENDAR_SCOPES)
        admin_client.table("integration_recoveries").delete().eq("user_id", user_id).execute()

        outlook_event = _approved_event(admin_client, user_id, google_calendar_event_id="outlook:E1")
        google_event = _approved_event(admin_client, user_id, google_calendar_event_id="googleid1")
        admin_client.table("calendar_work_items").update({
            "status": "blocked", "failure_code": "oauth_required", "attempts": 3,
        }).in_("event_id", [outlook_event, google_event]).execute()

        _connect(admin_client, user_id, "outlook", OUTLOOK_CALENDAR_SCOPES)
        recovery = None
        for _ in range(50):
            recovery = await claim_integration_recovery(pg_pool, "outlook-it", lock_seconds=120)
            if recovery is None or str(recovery["user_id"]) == str(user_id):
                break
        assert recovery is not None and recovery["provider"] == "outlook"

        requeued = await requeue_calendar_recovery_batch(pg_pool, recovery["id"], "outlook-it")
        assert requeued == 1

        items = {
            row["event_id"]: row
            for row in admin_client.table("calendar_work_items").select(
                "event_id,status,attempts,max_attempts"
            ).in_("event_id", [outlook_event, google_event]).execute().data
        }
        assert items[outlook_event]["status"] == "pending"
        assert items[outlook_event]["attempts"] < items[outlook_event]["max_attempts"]
        assert items[google_event]["status"] == "blocked"

        claimed = await _claim_for(pg_pool, user_id)
        assert claimed is not None and claimed["id"] == outlook_event
