"""`/events/*` (sync, unsync, apply-change, reject-change, undo) over a real SQLite database.

Requests carry real Selko access tokens; ownership, the delivery state and the
queued calendar work are read back from the database. Only the calendar
provider's reads (`get_calendar_event`, the divergence check) are mocked.

Moved here from `test_api_routes.py` (`TestServiceRoleOAuthRoutes`' event
tests, `TestEventUndo`), which stubbed the Supabase client.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from selko.api import deps
from selko.api.routes import events as event_routes
from selko.config import Config
from selko.db import runtime
from selko.db.codec import new_id
from selko.services import accounts
from selko.services.accounts import TokenKeys

SECRET = "e" * 40
FUTURE = "2030-01-01T10:00:00.000000Z"


@pytest.fixture
def api(db):
    runtime.use_database(db)
    app = FastAPI()
    app.include_router(event_routes.router)
    app.dependency_overrides[deps.get_config] = lambda: Config(environment="development", jwt_secret=SECRET)
    with TestClient(app) as c:
        yield c
    runtime.use_database(None)


def _user(db, email):
    accounts.sign_up(db, email, "secret-pw")
    signed = accounts.sign_in(db, TokenKeys(SECRET), email, "secret-pw")
    return signed.user["id"], {"Authorization": f"Bearer {signed.access_token}"}


@pytest.fixture
def owner(db):
    return _user(db, "owner@example.test")


@pytest.fixture
def stranger(db):
    return _user(db, "stranger@example.test")


def _event(factory, user, **extra):
    values = {"title": "Bike Fest", "start_datetime": FUTURE, "end_datetime": "2030-01-01T11:00:00.000000Z",
              "location": "Park"}
    values.update(extra)
    return factory.event(user, review_status=values.pop("review_status", "active"), **values)


def _item(factory, user, event, status, *, generation=1, action="upsert", **extra):
    return factory._insert("calendar_work_items", {
        "id": new_id(), "event_id": event, "user_id": user, "action": action, "generation": generation,
        "status": status, "desired_event": {"title": "Bike Fest"}, **extra,
    })


def _work(db, event):
    return [db.schema.decode("calendar_work_items", r) for r in db.query(
        "SELECT * FROM calendar_work_items WHERE event_id = ? ORDER BY generation", (event,))]


def _pending_change(factory, user, event, *, kind="material_update"):
    source = factory.event_source(event, factory.email(user, processing_status="processed"), source_type="update")
    return factory._insert("event_change_proposals", {
        "id": new_id(), "event_id": event, "user_id": user, "source_id": source, "kind": kind,
        "status": "pending",
        "change_set": {"kind": kind, "changes": [{"field": "location", "before": "Park", "after": "Plaza"}]},
        "event_snapshot_before": {"title": "Bike Fest", "start_datetime": FUTURE, "location": "Park",
                                  "review_status": "active"},
    })


# --- sync ----------------------------------------------------------------------


def test_event_sync_requires_auth(api):
    assert api.post(f"/events/{new_id()}/sync").status_code == 401


def test_event_sync_leaves_approved_event_for_worker(api, db, factory, owner):
    user, headers = owner
    event = _event(factory, user)
    _item(factory, user, event, "pending")

    response = api.post(f"/events/{event}/sync", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"event_id": event, "google_calendar_event_id": None, "synced_at": None,
                               "status": "approved"}
    assert [w["status"] for w in _work(db, event)] == ["pending"], "nothing re-queued"


def test_event_sync_accepts_worker_owned_syncing_state(api, db, factory, owner):
    """A worker winning the approval race is success-in-progress."""
    user, headers = owner
    event = _event(factory, user)
    _item(factory, user, event, "processing", locked_by="w", locked_until="2099-01-01T00:00:00.000000Z")

    response = api.post(f"/events/{event}/sync", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "syncing"
    assert len(_work(db, event)) == 1


def test_event_sync_requeues_sync_failed_event_for_worker(api, db, factory, owner):
    """Explicit retry restores a fresh worker attempt budget."""
    user, headers = owner
    event = _event(factory, user)
    _item(factory, user, event, "failed", attempts=3, failure_code="server_error")

    response = api.post(f"/events/{event}/sync", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    first, second = _work(db, event)
    assert (second["generation"], second["status"], second["attempts"]) == (2, "pending", 0)
    assert second["desired_event"]["title"] == "Bike Fest"
    assert second["desired_event"]["location"] == "Park"


def test_event_sync_refuses_an_unapproved_event(api, db, factory, owner):
    user, headers = owner
    event = _event(factory, user, review_status="pending_review")

    response = api.post(f"/events/{event}/sync", headers=headers)

    assert response.status_code == 400
    assert _work(db, event) == []


def test_event_sync_not_found(api, owner):
    _, headers = owner
    assert api.post(f"/events/{new_id()}/sync", headers=headers).status_code == 404


def test_another_users_event_is_not_found(api, db, factory, owner, stranger):
    user, _ = owner
    _, other_headers = stranger
    event = _event(factory, user)
    _item(factory, user, event, "failed")

    for action in ("sync", "unsync", "apply-change", "reject-change", "undo"):
        response = api.post(f"/events/{event}/{action}", headers=other_headers)
        assert response.status_code == 404, action
    assert len(_work(db, event)) == 1, "nothing queued for the owner by a stranger"


# --- unsync --------------------------------------------------------------------


# --- apply / reject change -------------------------------------------------------


def test_apply_change_applies_the_pending_proposal(api, db, factory, owner):
    """The route itself, not only the service under it (CLAUDE.md: a route no test calls)."""
    user, headers = owner
    event = _event(factory, user)
    proposal = _pending_change(factory, user, event)

    response = api.post(f"/events/{event}/apply-change", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"event_id": event, "status": "active"}
    assert factory.row("event_change_proposals", proposal)["status"] == "applied"
    assert factory.row("events", event)["location"] == "Plaza"
    assert [(w["action"], w["status"]) for w in _work(db, event)] == [("upsert", "pending")]


def test_reject_change_restores_and_resolves(api, db, factory, owner):
    user, headers = owner
    event = _event(factory, user, location="Plaza")
    proposal = _pending_change(factory, user, event)

    response = api.post(f"/events/{event}/reject-change", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"event_id": event, "status": "active"}
    assert factory.row("event_change_proposals", proposal)["status"] == "rejected"
    assert factory.row("events", event)["location"] == "Park", "the snapshot is restored"
    assert _work(db, event) == []


def test_change_routes_need_a_pending_proposal(api, factory, owner):
    user, headers = owner
    event = _event(factory, user)

    for action in ("apply-change", "reject-change"):
        response = api.post(f"/events/{event}/{action}", headers=headers)
        assert response.status_code == 400, action


# --- undo ----------------------------------------------------------------------


def test_undo_calendar_diverged_returns_409(api, db, factory, owner):
    """Diverged GCal edit returns 409 CALENDAR_DIVERGED."""
    from selko.services.calendars import CalendarDivergedError

    user, headers = owner
    event = _event(factory, user, google_calendar_event_id="gcal-1", synced_at="2029-12-01T00:00:00.000000Z")
    diverged = CalendarDivergedError(
        "edited in Google Calendar", ["title"],
        differences=[{"field": "title", "selko": "Original title", "google": "Edited title"}],
        google_event_url="https://calendar.google.com/event?eid=test",
    )

    with patch("selko.services.events.calendars.get_calendar_event", return_value={"etag": "v1"}), \
         patch("selko.services.events.calendars.assert_calendar_not_diverged", side_effect=diverged):
        resp = api.post(f"/events/{event}/undo", json={"force": False}, headers=headers)

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error"] == "CALENDAR_DIVERGED"
    assert "Google Calendar" in detail["detail"]
    assert detail["conflict"] == {
        "changed_fields": ["title"],
        "differences": [{"field": "title", "selko": "Original title", "google": "Edited title"}],
        "google_event_url": "https://calendar.google.com/event?eid=test",
    }
    assert _work(db, event) == []


def test_undo_force_succeeds(api, db, factory, owner):
    user, headers = owner
    event = _event(factory, user, google_calendar_event_id="gcal-1", synced_at="2029-12-01T00:00:00.000000Z")

    with patch("selko.services.events.calendars.get_calendar_event", return_value={"etag": "v1"}), \
         patch("selko.services.events.calendars.assert_calendar_not_diverged") as check:
        resp = api.post(f"/events/{event}/undo", json={"force": True}, headers=headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "pending_review"
    check.assert_not_called()
    (item,) = _work(db, event)
    assert (item["action"], item["force_overwrite"]) == ("cancel", True)
