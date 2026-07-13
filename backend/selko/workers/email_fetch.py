"""Scheduled email ingestion for Gmail and Outlook."""

from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from supabase import Client

from selko.config import Config
from selko.services.attachments import AttachmentError, store_attachment_bytes
from selko.services.email_folders import (
    PERMANENT_GMAIL_LABEL_IDS,
    upsert_discovered_folders,
)
from selko.services.emails import (
    EmailError,
    parse_gmail_message,
    save_emails,
    store_gmail_message_attachments,
)
from selko.services.gmail import (
    GmailError,
    GmailHistoryExpiredError,
    GmailMessageNotFoundError,
    build_service,
    build_initial_sync_query,
    fetch_history_message_ids,
    fetch_messages,
    get_credentials,
    get_full_message as get_gmail_full_message,
    get_message_metadata,
    get_user_profile,
    list_labels,
    list_message_ids,
)
from selko.services.outlook import (
    RESYNC_REQUIRED,
    OutlookError,
    fetch_mail_folders,
    fetch_message_changes,
    get_access_token,
    get_full_message as get_outlook_full_message,
    list_attachments,
    normalize_mail_folders,
    parse_outlook_message,
)

# Backwards-compatible patch point used by existing worker tests and callers.
get_full_message = get_outlook_full_message
from selko.services.scheduled_tasks import enqueue_scheduled_task

logger = logging.getLogger(__name__)

EMAIL_PROVIDERS = ("gmail", "outlook")


def _process_gmail_fetch_legacy(
    client: Client,
    config: Config,
    payload: dict[str, Any],
) -> None:
    """Fetch and save Gmail messages for one user."""
    user_id = payload.get("user_id")
    max_emails = payload.get("max_emails", 50)
    if not user_id:
        raise ValueError("Missing user_id in payload")

    logger.info("Fetching up to %s Gmail emails for user %s", max_emails, user_id)
    creds = get_credentials(client, config, user_id=user_id)
    if not creds:
        logger.warning("No Gmail integration found for user %s", user_id)
        return {"fetched": 0, "saved": 0, "attachments_downloaded": 0}

    try:
        service = build_service(creds)
        messages = fetch_messages(service, max_results=max_emails)
    except GmailError as exc:
        logger.error("Error fetching Gmail for user %s: %s", user_id, exc)
        raise

    if not messages:
        logger.info("No new Gmail emails found for user %s", user_id)
        return {"fetched": 0, "saved": 0, "attachments_downloaded": 0}

    try:
        parsed = [parse_gmail_message(message) for message in messages]
        saved_records = save_emails(client, parsed, user_id=user_id)
        logger.info("Saved %s Gmail emails for user %s", len(saved_records), user_id)
    except EmailError as exc:
        logger.error("Error saving Gmail emails for user %s: %s", user_id, exc)
        raise
    return {
        "fetched": len(messages),
        "saved": len(saved_records),
        "attachments_downloaded": 0,
    }


def _folder_classifier_gateway(client: Client, config: Config):
    """Build the same gateway used by API requests for background classification."""

    try:
        from selko.services.llm_gateway import LLMGateway
        from selko.services.llm_logging import LLMLoggingService
        from selko.services.llm_provider import create_provider
        from selko.services.quotas import QuotaService

        return LLMGateway(
            create_provider(config),
            LLMLoggingService(client),
            QuotaService(client),
        )
    except Exception as exc:
        logger.warning("Folder classifier is unavailable; folders default to included: %s", exc)
        return None


def _gmail_folder_descriptors(labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    descriptors = []
    for label in labels:
        label_id = label.get("id")
        if not label_id:
            continue
        name = label.get("name") or label_id
        is_system = label.get("type") == "system"
        descriptors.append({
            "id": label_id,
            "name": name,
            "full_path": name,
            "kind": "label",
            "is_system": is_system,
            "system_kind": "excluded" if label_id in PERMANENT_GMAIL_LABEL_IDS else "system",
        })
    return descriptors


def _eligible_gmail_message(
    message: dict[str, Any],
    excluded_label_ids: set[str],
) -> bool:
    labels = set(message.get("labelIds") or [])
    return not (labels & PERMANENT_GMAIL_LABEL_IDS) and not (labels & excluded_label_ids)


def _gmail_excluded_user_labels(client: Client, integration_id: str) -> tuple[set[str], list[str]]:
    result = (
        client.table("email_folders")
        .select("provider_folder_id,name")
        .eq("integration_id", integration_id)
        .eq("provider", "gmail")
        .eq("is_system", False)
        .eq("is_included", False)
        .execute()
    )
    rows = result.data or []
    return (
        {row["provider_folder_id"] for row in rows if row.get("provider_folder_id")},
        [row["name"] for row in rows if row.get("name")],
    )


def _store_email_record(
    client: Client,
    *,
    user_id: str,
    integration_id: str,
    parsed: dict[str, Any],
) -> list[dict[str, Any]]:
    folder_ids = set(parsed.get("provider_folder_ids") or [])
    if folder_ids:
        existing = (
            client.table("emails")
            .select("provider_folder_ids")
            .eq("user_id", user_id)
            .eq("email_provider", parsed.get("email_provider"))
            .eq("provider_message_id", parsed.get("provider_message_id"))
            .maybe_single()
            .execute()
        )
        if existing and existing.data:
            folder_ids.update(existing.data.get("provider_folder_ids") or [])
            parsed["provider_folder_ids"] = sorted(folder_ids)
    parsed["integration_id"] = integration_id
    return save_emails(client, [parsed], user_id=user_id)


def _process_gmail_reliable(
    client: Client,
    config: Config,
    payload: dict[str, Any],
    integration: dict[str, Any],
) -> dict[str, int]:
    """Synchronize Gmail by durable History cursor and complete result pages."""

    user_id = payload["user_id"]
    integration_id = integration["id"]
    creds = get_credentials(client, config, user_id=user_id)
    if not creds:
        logger.warning("No Gmail integration found for user %s", user_id)
        return
    service = build_service(creds)
    labels = list_labels(service)
    upsert_discovered_folders(
        client,
        user_id=user_id,
        integration_id=integration_id,
        provider="gmail",
        folders=_gmail_folder_descriptors(labels),
        gateway=_folder_classifier_gateway(client, config),
    )
    excluded_ids, excluded_names = _gmail_excluded_user_labels(client, integration_id)
    cursor = integration.get("sync_cursor")
    recovery = False
    if cursor:
        try:
            message_ids, new_cursor = fetch_history_message_ids(service, cursor)
        except GmailHistoryExpiredError:
            recovery = True
            message_ids = []
            new_cursor = ""
    else:
        profile = get_user_profile(service)
        new_cursor = profile.get("historyId")
        message_ids = []

    if not cursor or recovery:
        query_days = 15 if recovery else 14
        query = build_initial_sync_query(excluded_names, days=query_days)
        listed = list_message_ids(service, query=query)
        message_ids.extend(item["id"] for item in listed if item.get("id"))

    processed_ids: set[str] = set()
    saved_count = 0
    attachments_count = 0
    for message_id in message_ids:
        if message_id in processed_ids:
            continue
        processed_ids.add(message_id)
        try:
            metadata = get_message_metadata(service, message_id)
        except GmailMessageNotFoundError:
            # Gmail reports deletions in History; there is no content to ingest.
            continue
        if not _eligible_gmail_message(metadata, excluded_ids):
            continue
        try:
            message = get_gmail_full_message(service, message_id)
        except GmailMessageNotFoundError:
            continue
        if not _eligible_gmail_message(message, excluded_ids):
            continue
        parsed = parse_gmail_message(message)
        parsed["provider_folder_ids"] = [
            label_id
            for label_id in message.get("labelIds", [])
            if label_id not in PERMANENT_GMAIL_LABEL_IDS
        ]
        saved = _store_email_record(
            client,
            user_id=user_id,
            integration_id=integration_id,
            parsed=parsed,
        )
        if saved:
            saved_count += len(saved)
            if payload.get("fetch_attachments", True):
                attachments_count += store_gmail_message_attachments(
                    client,
                    config,
                    service,
                    message,
                    saved[0],
                    parsed,
                )

    # The cursor is committed only after every page, metadata check, full message,
    # upsert, and eligible attachment operation has completed.
    if not new_cursor:
        new_cursor = get_user_profile(service).get("historyId")
    if new_cursor:
        _save_sync_cursor(client, user_id, "gmail", new_cursor, include_last_sync=True)
    logger.info("Reliably synchronized %s Gmail messages for user %s", len(processed_ids), user_id)
    return {
        "fetched": len(processed_ids),
        "saved": saved_count,
        "attachments_downloaded": attachments_count,
    }


def _process_gmail_fetch_sync(
    client: Client,
    config: Config,
    payload: dict[str, Any],
) -> dict[str, int]:
    integration = _get_integration(client, payload.get("user_id", ""), "gmail")
    if isinstance(integration, dict) and integration.get("id"):
        return _process_gmail_reliable(client, config, payload, integration)
    # Compatibility for callers using an uninitialized mock/integration record.
    return _process_gmail_fetch_legacy(client, config, payload)


def _get_integration(client: Client, user_id: str, provider: str) -> dict[str, Any]:
    result = (
        client.table("integrations")
        .select("*")
        .eq("user_id", user_id)
        .eq("provider", provider)
        .maybe_single()
        .execute()
    )
    return result.data if result and result.data else {}


def _save_sync_cursor(
    client: Client,
    user_id: str,
    provider: str,
    cursor: str,
    *,
    include_last_sync: bool = False,
) -> None:
    update = {"sync_cursor": cursor}
    if include_last_sync:
        update["last_sync_at"] = datetime.now(timezone.utc).isoformat()
    client.table("integrations").update(
        update
    ).eq("user_id", user_id).eq("provider", provider).execute()


def _mark_outlook_message_removed(
    client: Client,
    user_id: str,
    provider_message_id: str,
    folder_id: str | None = None,
) -> None:
    if folder_id:
        _remove_outlook_folder_membership(
            client, user_id, provider_message_id, folder_id
        )
    else:
        logger.info(
            "Outlook message %s left an included folder; membership is unknown, not Trash",
            provider_message_id,
        )


def _store_outlook_attachments(
    client: Client,
    config: Config,
    user_id: str,
    email_id: str,
    message_id: str,
    token: str,
) -> None:
    for attachment in list_attachments(token, message_id):
        attachment_type = attachment.get("@odata.type")
        if attachment_type != "#microsoft.graph.fileAttachment":
            logger.info(
                "Skipping unsupported Outlook attachment type %s for message %s",
                attachment_type,
                message_id,
            )
            continue

        content = attachment.get("contentBytes")
        if not content:
            logger.warning("Outlook attachment %s has no contentBytes", attachment.get("id"))
            continue

        try:
            data = base64.b64decode(content, validate=True)
        except (ValueError, TypeError) as exc:
            logger.warning(
                "Skipping invalid base64 Outlook attachment %s: %s",
                attachment.get("id"),
                exc,
            )
            continue

        try:
            store_attachment_bytes(
                client,
                email_id,
                data=data,
                filename=attachment.get("name") or "unnamed",
                mime_type=attachment.get("contentType") or "application/octet-stream",
                config=config,
                provider_attachment_id=attachment.get("id") or "",
                user_id=user_id,
            )
        except AttachmentError as exc:
            logger.warning(
                "Failed to store Outlook attachment for message %s: %s",
                message_id,
                exc,
            )


def _process_outlook_fetch_legacy(
    client: Client,
    config: Config,
    payload: dict[str, Any],
) -> None:
    """Fetch Outlook Inbox changes through Microsoft Graph delta sync."""
    user_id = payload.get("user_id")
    if not user_id:
        raise ValueError("Missing user_id in payload")

    token = get_access_token(client, config, user_id)
    if not token:
        logger.warning("No Outlook integration found for user %s", user_id)
        return

    integration = _get_integration(client, user_id, "outlook")
    cursor = integration.get("sync_cursor")
    changes, new_cursor = fetch_message_changes(token, cursor)
    if new_cursor == RESYNC_REQUIRED:
        logger.info("Restarting Outlook full sync for user %s", user_id)
        changes, new_cursor = fetch_message_changes(token, None)
        if new_cursor == RESYNC_REQUIRED:
            raise OutlookError("Outlook delta cursor expired during full resync")

    for change in changes:
        message_id = change["id"]
        if change.get("removed"):
            _mark_outlook_message_removed(client, user_id, message_id)
            continue

        message = get_full_message(token, message_id)
        parsed = parse_outlook_message(message)
        try:
            saved = save_emails(client, [parsed], user_id=user_id)
        except EmailError:
            raise
        if not saved:
            continue
        _store_outlook_attachments(
            client,
            config,
            user_id,
            saved[0]["id"],
            message_id,
            token,
        )

    if new_cursor and new_cursor != RESYNC_REQUIRED:
        _save_sync_cursor(client, user_id, "outlook", new_cursor)

    logger.info(
        "Processed %s Outlook Inbox changes for user %s",
        len(changes),
        user_id,
    )


def _save_folder_cursor(
    client: Client,
    folder_row: dict[str, Any],
    cursor: str,
) -> None:
    client.table("email_folders").update({
        "sync_cursor": cursor,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq(
        "id", folder_row["id"]
    ).execute()


def _remove_outlook_folder_membership(
    client: Client,
    user_id: str,
    message_id: str,
    folder_id: str,
) -> None:
    """Reconcile a folder move without treating it as Trash."""

    result = (
        client.table("emails")
        .select("id,provider_folder_ids")
        .eq("user_id", user_id)
        .eq("email_provider", "outlook")
        .eq("provider_message_id", message_id)
        .maybe_single()
        .execute()
    )
    if not result or not result.data:
        return
    folder_ids = [
        value for value in (result.data.get("provider_folder_ids") or [])
        if value != folder_id
    ]
    client.table("emails").update({
        "provider_folder_ids": folder_ids,
    }).eq("id", result.data["id"]).execute()


def _outlook_folder_rows(client: Client, integration_id: str) -> list[dict[str, Any]]:
    result = (
        client.table("email_folders")
        .select("*")
        .eq("integration_id", integration_id)
        .eq("provider", "outlook")
        .execute()
    )
    return result.data or []


def _process_outlook_reliable(
    client: Client,
    config: Config,
    payload: dict[str, Any],
    integration: dict[str, Any],
) -> None:
    """Synchronize every included Outlook folder with an independent cursor."""

    user_id = payload["user_id"]
    token = get_access_token(client, config, user_id)
    if not token:
        logger.warning("No Outlook integration found for user %s", user_id)
        return

    integration_id = integration["id"]
    discovered = normalize_mail_folders(fetch_mail_folders(token))
    upsert_discovered_folders(
        client,
        user_id=user_id,
        integration_id=integration_id,
        provider="outlook",
        folders=discovered,
        gateway=_folder_classifier_gateway(client, config),
    )
    folder_rows = _outlook_folder_rows(client, integration_id)
    since = datetime.now(timezone.utc) - timedelta(days=14)

    for folder in folder_rows:
        if folder.get("is_system") or not folder.get("is_included"):
            # No Graph listing, delta, subscription, or message fetch is issued
            # for permanently excluded or user-excluded folders.
            continue
        cursor = folder.get("sync_cursor")
        try:
            changes, new_cursor = fetch_message_changes(
                token,
                cursor,
                folder_id=folder["provider_folder_id"],
                since=since if not cursor else None,
                immutable_ids=True,
            )
        except OutlookError:
            raise
        if new_cursor == RESYNC_REQUIRED:
            changes, new_cursor = fetch_message_changes(
                token,
                None,
                folder_id=folder["provider_folder_id"],
                since=since,
                immutable_ids=True,
            )
            if new_cursor == RESYNC_REQUIRED:
                raise OutlookError(
                    f"Outlook delta cursor expired during resync for folder {folder['full_path']}"
                )

        for change in changes:
            message_id = change["id"]
            if change.get("removed"):
                _remove_outlook_folder_membership(
                    client,
                    user_id,
                    message_id,
                    folder["provider_folder_id"],
                )
                continue
            message = get_outlook_full_message(token, message_id)
            parsed = parse_outlook_message(message, folder_id=folder["provider_folder_id"])
            saved = _store_email_record(
                client,
                user_id=user_id,
                integration_id=integration_id,
                parsed=parsed,
            )
            if saved:
                _store_outlook_attachments(
                    client,
                    config,
                    user_id,
                    saved[0]["id"],
                    message_id,
                    token,
                )

        if new_cursor:
            _save_folder_cursor(client, folder, new_cursor)

    logger.info("Reliably synchronized Outlook folders for user %s", user_id)


def _process_outlook_fetch_sync(
    client: Client,
    config: Config,
    payload: dict[str, Any],
) -> None:
    integration = _get_integration(client, payload.get("user_id", ""), "outlook")
    if isinstance(integration, dict) and integration.get("id"):
        _process_outlook_reliable(client, config, payload, integration)
        return
    _process_outlook_fetch_legacy(client, config, payload)


def _process_email_fetch_sync(
    client: Client,
    config: Config,
    payload: dict[str, Any],
) -> None:
    provider = payload.get("provider", "gmail")
    if provider == "gmail":
        _process_gmail_fetch_sync(client, config, payload)
    elif provider == "outlook":
        _process_outlook_fetch_sync(client, config, payload)
    else:
        raise ValueError(f"Unsupported email provider: {provider}")


async def process_email_fetch_task(
    client: Client,
    config: Config,
    payload: dict[str, Any],
) -> None:
    """Process an email_fetch task for Gmail or Outlook."""
    await asyncio.to_thread(_process_email_fetch_sync, client, config, payload)


async def process_email_fetch_job(
    client: Client,
    config: Config,
    job_id: str,
    payload: dict[str, Any],
) -> None:
    """Legacy wrapper retained for callers using the old job API."""
    await process_email_fetch_task(client, config, payload)


async def schedule_email_fetches() -> None:
    """Enqueue one deduplicated email fetch task per active provider account."""
    from selko.config import load_config
    from selko.services.auth import get_service_client

    config = load_config()
    client = get_service_client(config)

    try:
        result = client.table("integrations").select(
            "user_id,provider"
        ).in_("provider", list(EMAIL_PROVIDERS)).eq("status", "active").execute()

        integrations = {
            (row["user_id"], row["provider"])
            for row in result.data
            if row.get("user_id") and row.get("provider") in EMAIL_PROVIDERS
        }
        if not integrations:
            logger.debug("No users with active email integrations")
            return

        existing_result = client.table("scheduled_tasks").select(
            "user_id,payload"
        ).eq("task_type", "email_fetch").in_(
            "status", ["pending", "processing"]
        ).execute()
        existing_keys = set()
        for row in existing_result.data:
            payload = row.get("payload") or {}
            existing_keys.add((row.get("user_id"), payload.get("provider", "gmail")))

        tasks_created = 0
        tasks_skipped = 0
        for user_id, provider in sorted(integrations):
            if (user_id, provider) in existing_keys:
                tasks_skipped += 1
                continue
            try:
                enqueue_scheduled_task(
                    client,
                    user_id=user_id,
                    task_type="email_fetch",
                    payload={
                        "user_id": user_id,
                        "provider": provider,
                        "max_emails": 50,
                    },
                )
                tasks_created += 1
            except Exception as exc:
                logger.error(
                    "Failed to enqueue %s email_fetch for user %s: %s",
                    provider,
                    user_id,
                    exc,
                )

        logger.info(
            "Scheduled %s email fetches (%s skipped — already queued)",
            tasks_created,
            tasks_skipped,
        )
    except Exception as exc:
        logger.error("Failed to schedule email fetches: %s", exc, exc_info=True)
