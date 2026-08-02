"""Idempotently seed durable polling state from existing local email rows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from selko.config import load_config
from selko.services.auth import get_service_client


def main() -> None:
    config = load_config()
    client = get_service_client(config)
    integrations = client.table("integrations").select("id,user_id,provider").in_("provider", ["gmail", "outlook"]).eq("status", "active").execute().data or []
    states = 0
    items = 0
    for integration in integrations:
        state = client.table("email_sync_state").select("integration_id").eq("integration_id", integration["id"]).maybe_single().execute()
        if not state.data:
            client.table("email_sync_state").insert({
                "integration_id": integration["id"],
                "user_id": integration["user_id"],
                "provider": integration["provider"],
                "initial_watermark_at": (datetime.now(timezone.utc) - timedelta(days=14)).isoformat(),
            }).execute()
            states += 1
        rows = client.table("emails").select("id,user_id,email_provider,provider_message_id,provider_folder_ids").eq("integration_id", integration["id"]).execute().data or []
        for email in rows:
            client.table("email_ingestion_items").upsert({
                "integration_id": integration["id"],
                "user_id": email["user_id"],
                "provider": email["email_provider"],
                "provider_message_id": email["provider_message_id"],
                "provider_folder_ids": email.get("provider_folder_ids") or [],
                "acquisition_status": "completed",
                "email_id": email["id"],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="integration_id,provider_message_id").execute()
            items += 1
    print(f"backfill complete: integrations_created={states} email_items_seen={items}")


if __name__ == "__main__":
    main()
