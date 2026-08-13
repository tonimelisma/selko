"""C1 real-Postgres proof that component writes are wired and non-destructive."""

from uuid import uuid4

import pytest


@pytest.mark.integration
def test_calendar_components_survive_empty_resave(admin_client, temp_user) -> None:
    test_user_id = temp_user[0]
    provider_message_id = f"calendar-component-{uuid4()}"
    email_payload = {
        "email_provider": "gmail",
        "provider_message_id": provider_message_id,
        "subject": "calendar component probe",
        "from_email": "calendar-component@example.com",
        "provider_labels": ["INBOX"],
    }
    component = {
        "method": "CANCEL",
        "uid_hash": "a" * 64,
        "sequence": 4,
        "component_status": "CANCELLED",
        "start_datetime": "2026-08-20T13:00:00Z",
        "end_datetime": "2026-08-20T14:00:00Z",
    }
    first = admin_client.rpc(
        "save_email_with_attachment_descriptors",
        {
            "p_user_id": test_user_id,
            "p_email": email_payload,
            "p_descriptors": [],
            "p_calendar_components": [component],
        },
    ).execute()
    email_id = first.data
    assert email_id
    rows = (
        admin_client.table("email_calendar_components")
        .select("method,uid_hash,sequence,component_status")
        .eq("email_id", email_id)
        .execute()
        .data
    )
    assert rows == [{"method": "CANCEL", "uid_hash": "a" * 64, "sequence": 4, "component_status": "CANCELLED"}]

    admin_client.rpc(
        "save_email_with_attachment_descriptors",
        {
            "p_user_id": test_user_id,
            "p_email": email_payload,
            "p_descriptors": [],
            "p_calendar_components": [],
        },
    ).execute()
    preserved = (
        admin_client.table("email_calendar_components")
        .select("id")
        .eq("email_id", email_id)
        .execute()
        .data
    )
    assert len(preserved) == 1
