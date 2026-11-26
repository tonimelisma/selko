"""The web app's data API over a real SQLite database, and who may see what.

`test_every_route_refuses_another_users_ids` enumerates the router: a route
without a case below fails by name, so a new route cannot ship unchecked.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from selko.api import deps
from selko.api.limits import limiter
from selko.api.routes import client as client_routes
from selko.config import Config
from selko.db import runtime
from selko.services import accounts
from selko.services.accounts import TokenKeys

SECRET = "s" * 40


@pytest.fixture
def api(db):
    limiter.reset()
    runtime.use_database(db)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(client_routes.router)
    app.dependency_overrides[deps.get_config] = lambda: Config(environment="development", jwt_secret=SECRET)
    with TestClient(app) as c:
        yield c
    runtime.use_database(None)


def _bearer(db, email):
    accounts.sign_up(db, email, "secret-pw")
    signed = accounts.sign_in(db, TokenKeys(SECRET), email, "secret-pw")
    return signed.user["id"], {"Authorization": f"Bearer {signed.access_token}"}


@pytest.fixture
def world(db, factory):
    """User A owns one of everything; user B owns nothing."""
    a, a_headers = _bearer(db, "a@example.test")
    b, b_headers = _bearer(db, "b@example.test")
    email = factory.email(a, processing_status="processed", date_sent="2026-12-01T10:00:00.000000Z", has_attachments=True)
    future = "2030-01-01T10:00:00.000000Z"
    pending = factory.event(a, review_status="pending_review", start_datetime=future)
    active = factory.event(a, review_status="active", start_datetime=future, title="Kept")
    factory.event_source(pending, email_id=email)
    integration = factory.integration(a, provider="google_calendar")
    attachment = factory._insert("attachments", {
        "id": factory_id(), "user_id": a, "email_id": email, "filename": "ticket.pdf",
        "mime_type": "application/pdf", "storage_path": f"{a}/ticket.pdf", "ingestion_status": "stored",
    })
    rule = factory._insert("sender_rules", {"id": factory_id(), "user_id": a, "sender_email": "x@y.test", "action": "ignore"})
    return {"a": a, "b": b, "a_h": a_headers, "b_h": b_headers, "email": email, "pending": pending,
            "active": active, "integration": integration, "attachment": attachment, "rule": rule}


def factory_id():
    from selko.db.codec import new_id

    return new_id()


# --- behaviour ----------------------------------------------------------------


def test_review_queue_lists_new_events_with_their_sources(api, world):
    rows = api.get("/events/review", headers=world["a_h"]).json()
    assert [r["id"] for r in rows] == [world["pending"]]  # the active one has no pending change
    row = rows[0]
    assert row["status"] == "pending_review"
    assert row["event_sources"][0]["emails"]["id"] == world["email"]
    assert row["calendar_work_items"] == [] and row["event_change_proposals"] == []


def test_review_queue_is_bounded_soonest_first_and_says_how_many_wait(api, world, factory):
    later = [factory.event(world["a"], review_status="pending_review", start_datetime=f"2031-01-{d:02d}T10:00:00.000000Z")
             for d in range(1, 6)]
    response = api.get("/events/review?limit=3", headers=world["a_h"])
    assert response.status_code == 200
    assert response.headers["X-Total-Count"] == "6"
    assert [r["id"] for r in response.json()] == [world["pending"], *later[:2]]  # soonest first
    everything = api.get("/events/review", headers=world["a_h"])
    assert len(everything.json()) == 6 and everything.headers["X-Total-Count"] == "6"
    assert api.get("/events/review?limit=501", headers=world["a_h"]).status_code == 422


def test_email_history_orders_from_the_covering_index_not_the_rows(db, factory):
    """Ordering whole rows read every email body of the user on each page."""
    from selko.db import client as data

    user = factory.user()
    dated = [factory.email(user, processing_status="processed", date_sent=f"2026-0{m}-01T10:00:00.000000Z") for m in (1, 3, 2)]
    undated = factory.email(user, processing_status="processed", date_sent=None)
    factory.email(user, processing_status="pending")  # not history
    items, total = data.email_history(db, user, 10, 0)
    assert total == 4
    assert [e["id"] for e in items] == [undated, dated[1], dated[2], dated[0]]  # undated first, then newest
    assert [e["id"] for e in data.email_history(db, user, 2, 1)[0]] == [dated[1], dated[2]]
    where = ("user_id = ? AND (processing_status IN ('processed', 'failed')"
             " OR (processing_status = 'skipped' AND processing_outcome = 'calendar_invite'))")
    plan = " ".join(r[3] for r in db.query(
        f"EXPLAIN QUERY PLAN SELECT id FROM emails WHERE {where}"
        " ORDER BY date_sent IS NOT NULL, date_sent DESC, id DESC LIMIT 10", (user,)))
    assert "COVERING INDEX idx_emails_history_order" in plan, plan


def test_activity_pages_decided_events(api, world):
    page = api.get("/events/activity?limit=1", headers=world["a_h"]).json()
    assert page["total"] == 1 and [i["id"] for i in page["items"]] == [world["active"]]
    assert api.get("/events/activity?limit=0", headers=world["a_h"]).status_code == 422


def test_editing_an_event_returns_it_whole(api, world):
    edited = api.patch(f"/events/{world['pending']}", json={"title": "  Concert  "}, headers=world["a_h"])
    assert edited.status_code == 200
    body = edited.json()
    assert body["title"] == "Concert" and body["event_sources"] and body["status"] == "pending_review"
    assert api.patch(f"/events/{world['pending']}", json={"user_id": world["b"]}, headers=world["a_h"]).status_code == 422
    assert api.patch(f"/events/{world['pending']}", json={}, headers=world["a_h"]).status_code == 422


def test_accept_and_reject(api, world, db):
    accepted = api.post(f"/events/{world['pending']}/accept", headers=world["a_h"])
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["review_status"] == "active"
    assert db.query_one("SELECT count(*) FROM calendar_work_items WHERE event_id = ?", (world["pending"],))[0] == 1
    rejected = api.post(f"/events/{world['active']}/reject", headers=world["a_h"])
    assert rejected.status_code == 200 and rejected.json()["review_status"] == "rejected"


def test_email_history_and_details(api, world):
    history = api.get("/emails/history", headers=world["a_h"]).json()
    assert history["total"] == 1
    sources = history["items"][0]["event_sources"]
    assert sources[0]["events"]["id"] == world["pending"]
    email = api.get(f"/emails/{world['email']}", headers=world["a_h"]).json()
    assert set(email) == {"id", "email_provider", "subject", "from_email", "from_name", "date_sent", "snippet", "has_attachments"}
    assert api.get(f"/emails/{world['email']}/processing-state", headers=world["a_h"]).json()["processing_status"] == "processed"
    attachments = api.get(f"/emails/{world['email']}/attachments", headers=world["a_h"]).json()
    assert [a["filename"] for a in attachments] == ["ticket.pdf"] and "storage_path" not in attachments[0]


def test_attachment_download_streams_the_stored_file(api, world, db):
    folder = runtime.attachments_dir() / world["a"]
    folder.mkdir(parents=True)
    (folder / "ticket.pdf").write_bytes(b"%PDF-1.7 ticket")
    response = api.get(f"/attachments/{world['attachment']}/content", headers=world["a_h"])
    assert response.status_code == 200 and response.content == b"%PDF-1.7 ticket"
    assert response.headers["content-type"] == "application/pdf"
    assert "ticket.pdf" in response.headers["content-disposition"]


def test_attachment_path_cannot_escape_the_attachments_folder(api, world, db):
    with db.write() as tx:
        tx.execute("UPDATE attachments SET storage_path = '../selko.db' WHERE id = ?", (world["attachment"],))
    assert api.get(f"/attachments/{world['attachment']}/content", headers=world["a_h"]).status_code == 404


def test_integrations_never_carry_tokens(api, world):
    rows = api.get("/integrations", headers=world["a_h"]).json()
    assert len(rows) == 1 and not ({"access_token", "refresh_token"} & set(rows[0]))


def test_sender_rules_crud_and_duplicates(api, world):
    created = api.post("/sender-rules", json={"sender_domain": "spam.test", "action": "ignore"}, headers=world["a_h"])
    assert created.status_code == 201 and created.json()["user_id"] == world["a"]
    again = api.post("/sender-rules", json={"sender_domain": "spam.test", "action": "ignore"}, headers=world["a_h"])
    assert again.status_code == 409
    assert api.post("/sender-rules", json={"action": "ignore"}, headers=world["a_h"]).status_code == 422
    assert len(api.get("/sender-rules", headers=world["a_h"]).json()) == 2
    assert api.delete(f"/sender-rules/{created.json()['id']}", headers=world["a_h"]).status_code == 204


def test_calendar_settings_merge_and_validate(api, world):
    assert api.get("/settings/calendar", headers=world["a_h"]).json() == {"settings": None}
    saved = api.patch("/settings/calendar", json={"timezone": "Europe/Helsinki"}, headers=world["a_h"])
    assert saved.status_code == 200 and saved.json()["settings"]["timezone"] == "Europe/Helsinki"
    assert api.patch("/settings/calendar", json={"timezone": "Mars/Base"}, headers=world["a_h"]).status_code == 422
    bad = api.patch("/settings/calendar", json={"all_day_display_mode": "custom", "all_day_custom_start": "10:00",
                                                "all_day_custom_end": "09:00"}, headers=world["a_h"])
    assert bad.status_code == 422


def test_every_route_needs_a_token(api):
    for route in client_routes.router.routes:
        method = sorted(route.methods)[0]
        path = route.path.replace("{event_id}", factory_id()).replace("{email_id}", factory_id()) \
            .replace("{attachment_id}", factory_id()).replace("{rule_id}", factory_id())
        assert api.request(method, path, json={}).status_code == 401, (method, route.path)


# --- ownership: user B with user A's ids ------------------------------------

CASES = {
    ("GET", "/events/review"): None,
    ("GET", "/events/activity"): None,
    ("GET", "/events/{event_id}"): ("pending", None),
    ("PATCH", "/events/{event_id}"): ("pending", {"title": "stolen"}),
    ("POST", "/events/{event_id}/accept"): ("pending", None),
    ("POST", "/events/{event_id}/reject"): ("pending", None),
    ("GET", "/emails/history"): None,
    ("GET", "/emails/{email_id}"): ("email", None),
    ("GET", "/emails/{email_id}/processing-state"): ("email", None),
    ("GET", "/emails/{email_id}/attachments"): ("email", None),
    ("GET", "/attachments/{attachment_id}/content"): ("attachment", None),
    ("GET", "/integrations"): None,
    ("POST", "/integrations/disconnect"): ("integration", "body:integration_ids"),
    ("GET", "/integrations/recovery"): None,
    ("GET", "/sender-rules"): None,
    ("POST", "/sender-rules"): None,
    ("DELETE", "/sender-rules/{rule_id}"): ("rule", None),
    ("POST", "/sender-rules/ignore-sender"): None,
    ("GET", "/settings/calendar"): None,
    ("PATCH", "/settings/calendar"): None,
}


def test_every_route_refuses_another_users_ids(api, world, db):
    before = {t: db.query_one(f"SELECT count(*) FROM {t}")[0] for t in
              ("events", "integrations", "sender_rules", "calendar_work_items", "attachments")}
    titles = {r[0]: r[1] for r in db.query("SELECT id, title FROM events")}
    routes = {(sorted(r.methods)[0], r.path) for r in client_routes.router.routes}
    assert routes == set(CASES), f"routes without an ownership case: {sorted(routes - set(CASES))}"
    for (method, path), case in CASES.items():
        if case is None:
            continue  # no id: scoped to the caller by construction (covered by the behaviour tests)
        key, body = case
        target = world[key]
        if body == "body:integration_ids":
            response = api.request(method, path, json={"integration_ids": [target]}, headers=world["b_h"])
        else:
            concrete = path.split("{")[0] + target + (path.split("}")[1] if "}" in path else "")
            response = api.request(method, concrete, json=body, headers=world["b_h"])
        assert response.status_code == 404, (method, path, response.status_code, response.text)
    after = {t: db.query_one(f"SELECT count(*) FROM {t}")[0] for t in before}
    assert after == before
    assert {r[0]: r[1] for r in db.query("SELECT id, title FROM events")} == titles
    # And B's id-free lists are empty: nothing of A's leaks into them.
    for path in ("/events/review", "/events/activity", "/emails/history", "/integrations", "/sender-rules"):
        body = api.get(path, headers=world["b_h"]).json()
        items = body["items"] if isinstance(body, dict) else body
        assert items == [], path
