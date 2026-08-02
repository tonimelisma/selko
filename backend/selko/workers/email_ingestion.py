"""Dedicated durable polling, acquisition, and attachment workers."""

from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from supabase import Client

from selko.config import Config
from selko.services.attachments import (
    calculate_content_hash,
    download_gmail_attachment,
    upload_to_storage,
)
from selko.services.email_folders import upsert_discovered_folders
from selko.services.email_ingestion import (
    EmailIngestionRepository,
    ProviderMessageMissingError,
    SyncClaim,
    safe_error_code,
)
from selko.services.emails import parse_gmail_message, save_emails
from selko.services.gmail import (
    GmailHistoryExpiredError,
    GmailMessageNotFoundError,
    build_initial_sync_query,
    build_service,
    fetch_history_message_ids,
    get_credentials,
    get_message_metadata,
    get_user_profile,
    extract_attachments,
    extract_inline_images,
    list_labels,
    list_message_ids,
)
from selko.services.outlook import (
    GraphHttpError,
    RESYNC_REQUIRED,
    fetch_folder_messages,
    fetch_mail_folders,
    fetch_message_changes,
    get_access_token,
    get_full_message as get_outlook_full_message,
    list_attachments,
    normalize_mail_folders,
    parse_outlook_message,
    resolve_well_known_folder_ids,
)
from selko.services.msgraph import record_graph_failure

logger = logging.getLogger(__name__)

EMAIL_PROVIDERS = {"gmail", "outlook"}
SUPPORTED_ATTACHMENT_MIME_PREFIXES = ("image/", "text/")
SUPPORTED_ATTACHMENT_MIMES = {
    "application/pdf",
    "application/rtf",
    "application/ics",
    "text/calendar",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _chunks(values: Iterable[Any], size: int = 100) -> Iterable[list[Any]]:
    chunk: list[Any] = []
    for value in values:
        chunk.append(value)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _eligible_gmail_metadata(metadata: dict[str, Any], excluded: set[str]) -> bool:
    labels = set(metadata.get("labelIds") or [])
    permanent = {"SPAM", "TRASH", "DRAFT", "SENT", "CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_FORUMS"}
    return not labels.intersection(permanent | excluded)


class EmailIngestionWorker:
    """Coordinates v2 work while preserving one durable owner per item."""

    def __init__(self, client: Client, config: Config, worker_id: str):
        self.client = client
        self.config = config
        self.worker_id = worker_id
        self.repository = EmailIngestionRepository(client, config)
        self.stop_event = asyncio.Event()

    def stop(self) -> None:
        self.stop_event.set()

    async def run_sync_once(self) -> bool:
        claim = await asyncio.to_thread(self.repository.claim_due_sync, self.worker_id)
        if not claim:
            return await self.run_reconciliation_once()
        try:
            if self.config.email_ingestion_shadow_mode:
                logger.info("Email ingestion v2 shadow run provider=%s", claim.provider)
            else:
                await asyncio.to_thread(self.discover, claim)
            if not await asyncio.to_thread(self.repository.complete_sync, claim, self.worker_id):
                logger.warning("Email sync completion lost lease provider=%s", claim.provider)
        except Exception as exc:
            if isinstance(exc, GraphHttpError):
                record_graph_failure(
                    self.client,
                    self.config,
                    integration_id=claim.integration_id,
                    operation="sync",
                    url=getattr(exc, "safe_url_template", "/me/mailFolders/{folder-id}/messages/delta"),
                    error=exc,
                    run_id=claim.run_id,
                )
            logger.warning("Email sync failed provider=%s code=%s", claim.provider, safe_error_code(exc))
            await asyncio.to_thread(self.repository.fail_sync, claim, self.worker_id, exc)
        return True

    async def run_reconciliation_once(self) -> bool:
        claim = await asyncio.to_thread(self.repository.claim_due_reconciliation, self.worker_id)
        if not claim:
            return False
        try:
            days = self.config.email_reconcile_weekly_days if claim.run_kind == "weekly_reconcile" else self.config.email_reconcile_daily_days
            if not self.config.email_ingestion_shadow_mode:
                await asyncio.to_thread(self.reconcile, claim, days)
            await asyncio.to_thread(self.repository.complete_sync, claim, self.worker_id, reconciled=True)
        except Exception as exc:
            await asyncio.to_thread(self.repository.fail_sync, claim, self.worker_id, exc)
        return True

    def discover(self, claim: SyncClaim) -> None:
        if claim.provider == "gmail":
            self._discover_gmail(claim)
        elif claim.provider == "outlook":
            self._discover_outlook(claim)
        else:
            raise ValueError(f"Unsupported email provider: {claim.provider}")

    def _integration(self, integration_id: str) -> dict[str, Any]:
        result = self.client.table("integrations").select("*").eq("id", integration_id).single().execute()
        return result.data

    def _discover_gmail(self, claim: SyncClaim, *, lookback_days: int | None = None) -> None:
        integration = self._integration(claim.integration_id)
        credentials = get_credentials(self.client, self.config, user_id=claim.user_id)
        if not credentials:
            raise ProviderMessageMissingError("Gmail credentials are unavailable")
        service = build_service(credentials)
        labels = list_labels(service)
        excluded_result = (
            self.client.table("email_folders")
            .select("provider_folder_id")
            .eq("integration_id", claim.integration_id)
            .eq("provider", "gmail")
            .eq("is_included", False)
            .execute()
        )
        excluded = {row.get("provider_folder_id") for row in (excluded_result.data or [])}
        upsert_discovered_folders(
            self.client,
            user_id=claim.user_id,
            integration_id=claim.integration_id,
            provider="gmail",
            folders=[
                {
                    "id": label.get("id"),
                    "name": label.get("name") or label.get("id"),
                    "full_path": label.get("name") or label.get("id"),
                    "kind": "label",
                    "is_system": label.get("type") == "system",
                    "is_scannable": label.get("id") not in {"SPAM", "TRASH", "DRAFT", "SENT", "CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_FORUMS"},
                    "is_permanently_excluded": label.get("id") in {"SPAM", "TRASH", "DRAFT", "SENT", "CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_FORUMS"},
                }
                for label in labels if label.get("id")
            ],
        )
        cursor = integration.get("sync_cursor")
        replacement_cursor = get_user_profile(service).get("historyId")
        if lookback_days is not None or not cursor:
            query = build_initial_sync_query(days=lookback_days or 14)
            identities = [row.get("id") for row in list_message_ids(service, query=query) if row.get("id")]
            next_cursor = None if lookback_days is not None else replacement_cursor
        else:
            try:
                identities, next_cursor = fetch_history_message_ids(service, cursor)
            except GmailHistoryExpiredError:
                # Capture the replacement history boundary before the bounded
                # listing so new mail arriving during reconciliation is not lost.
                replacement_cursor = get_user_profile(service).get("historyId")
                identities = [row.get("id") for row in list_message_ids(service, query=build_initial_sync_query()) if row.get("id")]
                next_cursor = None if lookback_days is not None else replacement_cursor

        discovered: list[dict[str, Any]] = []
        for identity in identities:
            try:
                metadata = get_message_metadata(service, identity)
            except GmailMessageNotFoundError:
                discovered.append({"provider_message_id": identity, "change_kind": "removed"})
                continue
            folder_ids = sorted(set(metadata.get("labelIds") or []))
            discovered.append({
                "provider_message_id": identity,
                "provider_folder_ids": folder_ids,
                "change_kind": "upsert" if _eligible_gmail_metadata(metadata, excluded) else "removed",
            })
            if len(discovered) >= 100:
                self.repository.require_heartbeat(claim.integration_id, self.worker_id)
                self.repository.upsert_discovered(claim, discovered)
                discovered = []
        if discovered or next_cursor or lookback_days is not None:
            self.repository.require_heartbeat(claim.integration_id, self.worker_id)
            self.repository.upsert_discovered(claim, discovered, cursor=next_cursor)

    def _discover_outlook(self, claim: SyncClaim, *, lookback_days: int | None = None) -> None:
        token = get_access_token(self.client, self.config, claim.user_id)
        if not token:
            raise ProviderMessageMissingError("Outlook credentials are unavailable")
        try:
            resolved = resolve_well_known_folder_ids(token)
            discovered = normalize_mail_folders(fetch_mail_folders(token, resolved_well_known_ids=resolved))
        except GraphHttpError as exc:
            if exc.status_code != 401:
                raise
            # A single bounded refresh handles an expired access token without
            # replaying an entire mailbox pass indefinitely.
            token = get_access_token(self.client, self.config, claim.user_id, force_refresh=True)
            resolved = resolve_well_known_folder_ids(token)
            discovered = normalize_mail_folders(fetch_mail_folders(token, resolved_well_known_ids=resolved))
        upsert_discovered_folders(
            self.client,
            user_id=claim.user_id,
            integration_id=claim.integration_id,
            provider="outlook",
            folders=discovered,
        )
        rows = (
            self.client.table("email_folders")
            .select("*")
            .eq("integration_id", claim.integration_id)
            .eq("provider", "outlook")
            .execute()
        )
        failures: list[BaseException] = []
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days or 14)
        for folder in rows.data or []:
            if not folder.get("is_included") or not folder.get("is_scannable", True):
                continue
            try:
                if lookback_days is not None:
                    changes = fetch_folder_messages(token, folder["provider_folder_id"], since=since)
                    cursor = None
                else:
                    changes, cursor = fetch_message_changes(
                        token,
                        folder.get("sync_cursor"),
                        folder_id=folder["provider_folder_id"],
                        since=since if not folder.get("sync_cursor") else None,
                        immutable_ids=True,
                    )
                    if cursor == RESYNC_REQUIRED:
                        changes, cursor = fetch_message_changes(
                            token, None, folder_id=folder["provider_folder_id"], since=since, immutable_ids=True
                        )
                pages = list(_chunks(changes))
                for page_index, page in enumerate(pages):
                    items = [
                        {
                            "provider_message_id": change.get("id"),
                            "provider_folder_ids": [folder["provider_folder_id"]],
                            "change_kind": "removed" if change.get("removed") else "upsert",
                        }
                        for change in page if change.get("id")
                    ]
                    is_last = page_index == len(pages) - 1
                    self.repository.require_heartbeat(claim.integration_id, self.worker_id)
                    self.repository.upsert_discovered(
                        claim,
                        items,
                        cursor=cursor if is_last else None,
                        folder_id=folder["id"] if cursor and is_last else None,
                    )
                if not pages and cursor:
                    # An empty delta page can still be the completed page that
                    # carries the new opaque delta link.
                    self.repository.require_heartbeat(claim.integration_id, self.worker_id)
                    self.repository.upsert_discovered(
                        claim, [], cursor=cursor, folder_id=folder["id"]
                    )
            except GraphHttpError as exc:
                record_graph_failure(
                    self.client, self.config,
                    integration_id=claim.integration_id,
                    operation="folder_delta",
                    url=getattr(exc, "safe_url_template", "/me/mailFolders/{folder-id}/messages/delta"),
                    error=exc,
                    run_id=claim.run_id,
                )
                if exc.status_code == 404:
                    self.client.table("email_folders").delete().eq("id", folder["id"]).execute()
                    continue
                failures.append(exc)
            except Exception as exc:
                failures.append(exc)
        if failures:
            raise failures[0]

    def reconcile(self, claim: SyncClaim, lookback_days: int) -> None:
        """Run cursorless reconciliation; normal cursor state is untouched."""
        if claim.provider == "gmail":
            self._discover_gmail(claim, lookback_days=lookback_days)
        elif claim.provider == "outlook":
            self._discover_outlook(claim, lookback_days=lookback_days)

    async def run_acquisition_once(self) -> bool:
        item = await asyncio.to_thread(self.repository.claim_item, self.worker_id)
        if not item:
            return False
        try:
            if item.get("change_kind") == "removed":
                await asyncio.to_thread(self.repository.remove_item, item["id"], self.worker_id)
                return True
            email_id = await asyncio.to_thread(self.acquire_item, item)
            if not await asyncio.to_thread(self.repository.complete_item, item["id"], self.worker_id, email_id):
                logger.warning("Email acquisition completion lost lease")
        except (GraphHttpError, ProviderMessageMissingError) as exc:
            if getattr(exc, "status_code", None) == 404 or isinstance(exc, ProviderMessageMissingError):
                await asyncio.to_thread(self.repository.remove_item, item["id"], self.worker_id)
            else:
                await asyncio.to_thread(self.repository.fail_item, item["id"], self.worker_id, exc)
        except Exception as exc:
            await asyncio.to_thread(self.repository.fail_item, item["id"], self.worker_id, exc, terminal=safe_error_code(exc) == "parse_invalid")
        return True

    def acquire_item(self, item: dict[str, Any]) -> str:
        provider = item["provider"]
        if provider == "gmail":
            credentials = get_credentials(self.client, self.config, user_id=item["user_id"])
            if not credentials:
                raise ProviderMessageMissingError("Gmail credentials are unavailable")
            message = __import__("selko.services.gmail", fromlist=["get_full_message"]).get_full_message(
                build_service(credentials), item["provider_message_id"]
            )
            parsed = parse_gmail_message(message)
            parsed["integration_id"] = item["integration_id"]
            parsed["provider_folder_ids"] = item.get("provider_folder_ids") or parsed.get("provider_folder_ids") or []
            saved = save_emails(self.client, [parsed], user_id=item["user_id"])
            if not saved:
                raise RuntimeError("email upsert returned no row")
            descriptors = [
                {
                    "provider_attachment_id": d.get("attachment_id"),
                    "filename": d.get("filename"),
                    "mime_type": d.get("mime_type"),
                    "size_bytes": d.get("size_bytes"),
                }
                for d in extract_attachments(message) + extract_inline_images(message)
            ]
        elif provider == "outlook":
            token = get_access_token(self.client, self.config, item["user_id"])
            if not token:
                raise ProviderMessageMissingError("Outlook credentials are unavailable")
            message = get_outlook_full_message(token, item["provider_message_id"])
            parsed = parse_outlook_message(message)
            parsed["integration_id"] = item["integration_id"]
            parsed["provider_folder_ids"] = item.get("provider_folder_ids") or parsed.get("provider_folder_ids") or []
            saved = save_emails(self.client, [parsed], user_id=item["user_id"])
            if not saved:
                raise RuntimeError("email upsert returned no row")
            descriptors = [
                {
                    "provider_attachment_id": d.get("id"),
                    "filename": d.get("name"),
                    "mime_type": d.get("contentType"),
                    "size_bytes": d.get("size"),
                }
                for d in list_attachments(token, item["provider_message_id"])
            ]
        else:
            raise ValueError(f"Unsupported email provider: {provider}")
        self.repository.ensure_attachment_descriptors(item["email_id"] if item.get("email_id") else saved[0]["id"], item["user_id"], descriptors)
        return saved[0]["id"]

    async def run_attachment_once(self) -> bool:
        attachment = await asyncio.to_thread(self.repository.claim_attachment, self.worker_id)
        if not attachment:
            return False
        try:
            status = await asyncio.to_thread(self.acquire_attachment, attachment)
            await asyncio.to_thread(self.repository.finish_attachment, attachment["id"], self.worker_id, status)
        except Exception as exc:
            terminal = attachment.get("attempts", 0) >= attachment.get("max_attempts", 8)
            await asyncio.to_thread(
                self.repository.finish_attachment,
                attachment["id"], self.worker_id,
                "dead_letter" if terminal else "retry", safe_error_code(exc),
            )
        return True

    def acquire_attachment(self, attachment: dict[str, Any]) -> str:
        mime = str(attachment.get("mime_type") or "application/octet-stream").lower()
        if not (mime.startswith(SUPPORTED_ATTACHMENT_MIME_PREFIXES) or mime in SUPPORTED_ATTACHMENT_MIMES):
            return "unsupported"
        email = self.client.table("emails").select("user_id,email_provider,provider_message_id,integration_id").eq("id", attachment["email_id"]).single().execute().data
        if email["email_provider"] == "gmail":
            credentials = get_credentials(self.client, self.config, user_id=email["user_id"])
            if not credentials:
                raise ProviderMessageMissingError("Gmail credentials are unavailable")
            message = __import__("selko.services.gmail", fromlist=["get_full_message"]).get_full_message(build_service(credentials), email["provider_message_id"])
            # Inline images are registered as descriptors during acquisition but
            # are skipped by extract_attachments(), so both sources must be
            # searched or every CID image would be marked unsupported.
            candidates = extract_attachments(message) + extract_inline_images(message)
            descriptor = next((d for d in candidates if d.get("attachment_id") == attachment["provider_attachment_id"]), None)
            if not descriptor:
                return "unsupported"
            data = download_gmail_attachment(build_service(credentials), email["provider_message_id"], descriptor["attachment_id"])
        else:
            token = get_access_token(self.client, self.config, email["user_id"])
            if not token:
                raise ProviderMessageMissingError("Outlook credentials are unavailable")
            descriptor = next((d for d in list_attachments(token, email["provider_message_id"]) if d.get("id") == attachment["provider_attachment_id"]), None)
            if not descriptor or descriptor.get("@odata.type") != "#microsoft.graph.fileAttachment":
                return "unsupported"
            data = base64.b64decode(descriptor.get("contentBytes") or "", validate=True)
        content_hash = calculate_content_hash(data)
        storage_path = upload_to_storage(self.client, email["user_id"], attachment.get("filename") or "unnamed", data, mime, self.config.storage_bucket_attachments)
        self.client.table("attachments").update({
            "storage_path": storage_path,
            "content_hash": content_hash,
            "size_bytes": len(data),
        }).eq("id", attachment["id"]).eq("locked_by", self.worker_id).execute()
        return "stored"

    async def coordinator_loop(self) -> None:
        while not self.stop_event.is_set():
            did_work = await self.run_sync_once()
            if not did_work:
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=max(self.config.email_coordinator_tick_seconds, 1))
                except asyncio.TimeoutError:
                    pass

    async def acquisition_loop(self) -> None:
        while not self.stop_event.is_set():
            if not await self.run_acquisition_once():
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=1)
                except asyncio.TimeoutError:
                    pass

    async def attachment_loop(self) -> None:
        while not self.stop_event.is_set():
            if not await self.run_attachment_once():
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=1)
                except asyncio.TimeoutError:
                    pass

    async def run(self) -> None:
        await asyncio.gather(self.coordinator_loop(), self.acquisition_loop(), self.attachment_loop())
