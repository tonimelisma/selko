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
    assert len(rows("calendar_work_items")) == 4

    assert Counter(item["status"] for item in event_rows) == Counter({
        "pending_review": 2,
        "synced": 2,
        "approved": 1,
        "rejected": 1,
        "sync_failed": 1,
    })
    assert Counter(item["status"] for item in rows("calendar_work_items")) == Counter({
        "succeeded": 2,
        "pending": 1,
        "blocked": 1,
    })

    proposal = rows("event_change_proposals", "event_id,status,kind")[0]
    assert proposal["status"] == "pending"
    assert proposal["kind"] == "material_update"
    q2 = admin_client.table("events").select("review_status").eq(
        "id", proposal["event_id"]
    ).single().execute().data
    assert q2["review_status"] == "active"
