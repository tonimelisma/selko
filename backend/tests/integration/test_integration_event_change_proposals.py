"""Real-Postgres contracts for S3 proposal ownership and transitions."""

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.development]


def _snapshot(title: str = "before") -> dict:
    return {
        "title": title,
        "start_datetime": "2026-09-01T14:00:00Z",
        "end_datetime": "2026-09-01T15:00:00Z",
        "all_day": False,
        "location": None,
        "description": None,
        "importance": "action_required",
        "status": "approved",
    }


def _change_set(before: str = "before", after: str = "after") -> dict:
    return {
        "kind": "material_update",
        "changes": [{"field": "title", "before": before, "after": after}],
    }


def _event(admin_client, user_id: str, title: str = "proposal event") -> str:
    return admin_client.table("events").insert({
        "user_id": user_id,
        "title": title,
        "start_datetime": "2026-09-01T14:00:00Z",
        "end_datetime": "2026-09-01T15:00:00Z",
        "status": "pending_review",
    }).execute().data[0]["id"]


def _source(admin_client, event_id: str, email_id: str, before: str = "before", after: str = "after") -> str:
    return admin_client.table("event_sources").insert({
        "event_id": event_id,
        "email_id": email_id,
        "source_type": "update",
        "extracted_data": {"title": after},
        "event_snapshot_before": _snapshot(before),
        "change_set": _change_set(before, after),
    }).execute().data[0]["id"]


@pytest.mark.asyncio
async def test_proposal_is_authoritative_and_apply_reject_reopen_are_atomic(
    admin_client, temp_user
):
    user_id = temp_user[0]
    email_id = admin_client.table("emails").insert({
        "user_id": user_id,
        "email_provider": "gmail",
        "provider_message_id": "s3-proposal-atomic",
        "subject": "proposal",
    }).execute().data[0]["id"]
    event_id = _event(admin_client, user_id)
    source_id = _source(admin_client, event_id, email_id)
    proposal = admin_client.table("event_change_proposals").select(
        "id,status,source_id,kind"
    ).eq("source_id", source_id).single().execute().data
    assert proposal["status"] == "applied"
    assert proposal["kind"] == "material_update"

    admin_client.table("events").update({"status": "pending_change"}).eq("id", event_id).execute()
    admin_client.table("event_change_proposals").update({
        "status": "pending", "resolution_reason": None,
    }).eq("id", proposal["id"]).execute()
    applied = admin_client.rpc("apply_event_change_proposal", {
        "p_event_id": event_id,
        "p_user_id": user_id,
        "p_proposal_id": proposal["id"],
        "p_expected_hash": None,
        "p_title": "after",
        "p_start_datetime": "2026-09-01T14:00:00Z",
        "p_end_datetime": "2026-09-01T15:00:00Z",
        "p_all_day": False,
        "p_location": None,
        "p_description": None,
        "p_importance": "action_required",
        "p_next_status": "approved",
        "p_calendar_sync_action": "upsert",
    }).execute().data
    assert applied["proposal_id"] == proposal["id"]
    assert admin_client.table("event_change_proposals").select("status").eq(
        "id", proposal["id"]
    ).single().execute().data["status"] == "applied"

    reopened = admin_client.rpc("reopen_event_change_proposal", {
        "p_event_id": event_id,
        "p_user_id": user_id,
        "p_proposal_id": proposal["id"],
        "p_expected_hash": None,
    }).execute().data
    assert reopened["status"] == "pending_change"
    assert admin_client.table("events").select("status").eq(
        "id", event_id
    ).single().execute().data["status"] == "pending_change"


@pytest.mark.asyncio
async def test_new_proposal_supersedes_only_the_previous_pending_proposal(
    admin_client, temp_user
):
    user_id = temp_user[0]
    email_id = admin_client.table("emails").insert({
        "user_id": user_id,
        "email_provider": "gmail",
        "provider_message_id": "s3-proposal-replace",
    }).execute().data[0]["id"]
    event_id = _event(admin_client, user_id, "replacement")
    first_source = _source(admin_client, event_id, email_id, "one", "two")
    admin_client.table("events").update({"status": "pending_change"}).eq("id", event_id).execute()
    first = admin_client.table("event_change_proposals").select("id").eq(
        "source_id", first_source
    ).single().execute().data["id"]
    admin_client.table("event_change_proposals").update({
        "status": "pending", "resolution_reason": None,
    }).eq("id", first).execute()

    second_email_id = admin_client.table("emails").insert({
        "user_id": user_id,
        "email_provider": "gmail",
        "provider_message_id": "s3-proposal-replace-2",
    }).execute().data[0]["id"]
    second_source = _source(admin_client, event_id, second_email_id, "two", "three")
    rows = admin_client.table("event_change_proposals").select(
        "id,status,source_id"
    ).eq("event_id", event_id).execute().data
    by_id = {row["id"]: row for row in rows}
    assert by_id[first]["status"] == "superseded"
    second = next(row for row in rows if row["source_id"] == second_source)
    assert second["status"] == "pending"
    assert sum(row["status"] == "pending" for row in rows) == 1
