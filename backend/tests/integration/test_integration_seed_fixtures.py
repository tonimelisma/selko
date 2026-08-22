"""The screenshot fixture must be created through real application write paths."""

from collections import Counter

import pytest

from selko.services.users import list_users


SCREENSHOT_EMAIL = "screenshots@selko.local"


@pytest.mark.integration
def test_screenshot_seed_has_complete_lane_and_work_state(admin_client, config):
    user = next((item for item in list_users(config) if item["email"] == SCREENSHOT_EMAIL), None)
    assert user is not None, "verify.sh must seed the screenshot user before integration tests"
    user_id = user["id"]

    def rows(table, columns="*"):
        result = admin_client.table(table).select(columns).eq("user_id", user_id).execute()
        return result.data

    assert any(item["email"] == SCREENSHOT_EMAIL for item in list_users(config))
    assert len(rows("integrations")) == 2
    assert len(rows("email_folders")) == 2
    assert len(rows("emails")) == 5
    event_rows = rows("events")
    event_ids = [item["id"] for item in event_rows]
    assert len(event_rows) == 7
    source_rows = admin_client.table("event_sources").select("*").in_("event_id", event_ids).execute().data
    assert len(source_rows) == 8
    assert len(rows("event_change_proposals")) == 1
    work_items = rows("calendar_work_items")

    # Two owners, asserted separately. review_status owns the user's decision;
    # calendar_work_items owns delivery. The predecessor of this block asserted
    # a single events.status distribution -- pending_review 2, synced 2,
    # approved 1, rejected 1, sync_failed 1 -- against a column 20260829000001
    # deleted. The same five lanes are still here; they are just spread across
    # the two owners that replaced it.
    assert Counter(item["review_status"] for item in event_rows) == Counter({
        "active": 4,        # 2 delivered, 1 queued, 1 failed
        "pending_review": 2,
        "rejected": 1,
    })

    assert Counter(item["status"] for item in work_items) == Counter({
        "succeeded": 2,     # was synced
        "pending": 1,       # was approved
        "blocked": 1,       # was sync_failed
        "superseded": 1,    # Q2's re-enqueue history
    })

    # The invariant that matters more than any count: an event has at most one
    # work item that is not superseded, so a delivery state derived from
    # "latest non-superseded item" is never ambiguous.
    live_by_event = Counter(
        item["event_id"] for item in work_items if item["status"] != "superseded"
    )
    assert live_by_event and max(live_by_event.values()) == 1, live_by_event
    assert len(live_by_event) == 4

    proposal = rows("event_change_proposals", "event_id,status,kind")[0]
    assert proposal["status"] == "pending"
    assert proposal["kind"] == "material_update"
    q2 = admin_client.table("events").select("review_status").eq(
        "id", proposal["event_id"]
    ).single().execute().data
    assert q2["review_status"] == "active"
