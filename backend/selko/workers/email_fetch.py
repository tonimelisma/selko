"""Scheduled email ingestion for Gmail and Outlook."""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

from supabase import Client

from selko.config import Config
from selko.services.attachments import AttachmentError, store_attachment_bytes
from selko.services.emails import EmailError, parse_gmail_message, save_emails
from selko.services.gmail import GmailError, build_service, fetch_messages, get_credentials
from selko.services.outlook import (
    RESYNC_REQUIRED,
    OutlookError,
    fetch_message_changes,
    get_access_token,
    get_full_message,
    list_attachments,
    parse_outlook_message,
)
from selko.services.scheduled_tasks import enqueue_scheduled_task

logger = logging.getLogger(__name__)

EMAIL_PROVIDERS = ("gmail", "outlook")


def _process_gmail_fetch_sync(
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
        return

    try:
        service = build_service(creds)
        messages = fetch_messages(service, max_results=max_emails)
    except GmailError as exc:
        logger.error("Error fetching Gmail for user %s: %s", user_id, exc)
        raise

    if not messages:
        logger.info("No new Gmail emails found for user %s", user_id)
        return

    try:
        parsed = [parse_gmail_message(message) for message in messages]
        saved_records = save_emails(client, parsed, user_id=user_id)
        logger.info("Saved %s Gmail emails for user %s", len(saved_records), user_id)
    except EmailError as exc:
        logger.error("Error saving Gmail emails for user %s: %s", user_id, exc)
        raise


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
) -> None:
    client.table("integrations").update(
        {"sync_cursor": cursor}
    ).eq("user_id", user_id).eq("provider", provider).execute()


def _mark_outlook_message_removed(
    client: Client,
    user_id: str,
    provider_message_id: str,
) -> None:
    try:
        client.table("emails").update(
            {"is_trash": True}
        ).eq("user_id", user_id).eq(
            "email_provider", "outlook"
        ).eq("provider_message_id", provider_message_id).execute()
    except Exception as exc:
        logger.warning(
            "Could not mark removed Outlook message %s as trash: %s",
            provider_message_id,
            exc,
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


def _process_outlook_fetch_sync(
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
