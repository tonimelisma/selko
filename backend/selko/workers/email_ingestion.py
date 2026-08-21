"""Dedicated durable polling, acquisition, and attachment workers."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
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
    ProviderAuthenticationError,
    ProviderMessageMissingError,
    SyncClaim,
    safe_error_code,
)
from selko.services.emails import parse_gmail_message
from selko.services.ics_parser import parse_calendar_components
import selko.services.gmail as gmail  # 8a: module import keeps patch target stable

from selko.services.gmail import (
    GmailHistoryExpiredError,
    build_initial_sync_query,
    build_service,
    fetch_history_message_ids,
    get_full_message as get_gmail_full_message,
    get_gmail_credentials,
    get_messages_metadata_batch,
    get_user_profile,
    extract_attachments,
    extract_inline_images,
    list_labels,
    list_message_ids,
)

# 8a/8c: canonical names are get_gmail_credentials and get_gmail_full_message.
# Keep old patch targets working: tests patch selko.workers.email_ingestion.get_credentials
# (old name) and selko.services.gmail.get_full_message. Both must hit.
get_credentials = get_gmail_credentials  # old alias for 8c compat
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
from selko.services.msgraph import GraphCallContext, record_graph_failure
from selko.workers.concurrency import _try_acquire

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


def _accumulate_page_totals(totals: dict[str, int], page: dict[str, int] | None) -> None:
    """Merge one ``upsert_discovered`` page result into running totals."""
    if not page:
        return
    for key in ("provider_ids_seen", "items_inserted", "items_existing"):
        totals[key] = totals.get(key, 0) + int(page.get(key) or 0)


def _eligible_gmail_metadata(metadata: dict[str, Any], excluded: set[str]) -> bool:
    labels = set(metadata.get("labelIds") or [])
    permanent = {"SPAM", "TRASH", "DRAFT", "SENT", "CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_FORUMS"}
    return not labels.intersection(permanent | excluded)


class EmailIngestionWorker:
    """Coordinates v2 work while preserving one durable owner per item."""

    def __init__(self, client: Client, config: Config, worker_id: str, *, pg_pool=None, work_listener=None):
        self.client = client
        self.config = config
        self.worker_id = worker_id
        self.repository = EmailIngestionRepository(config, pg_pool)
        self._work_listener = work_listener
        # C4: executor width, NOT poller count. One claim loop per type drains
        # the queue; these bound how many items are processed concurrently.
        # The semaphore is acquired BEFORE the claim so a claimed row never
        # waits in a queue holding a lease.
        self._acquisition_semaphore = asyncio.Semaphore(
            max(int(getattr(config, "email_acquisition_concurrency", 2) or 2), 1)
        )
        self._attachment_semaphore = asyncio.Semaphore(
            max(int(getattr(config, "email_attachment_concurrency", 2) or 2), 1)
        )
        self._acquisition_inflight: set[asyncio.Task] = set()
        self._attachment_inflight: set[asyncio.Task] = set()
        self.stop_event = asyncio.Event()
        # Egress 5: in-process nudge for user-initiated email sync (same loop-bound
        # constraint as WorkerPool — created per runtime, cleared on wake).
        self._nudge_event: asyncio.Event | None = None
        # R3: claim loops also nudge-aware so discovery->acquisition is <100ms
        # not up to 30s geometric backoff. Separate event so coordinator nudge
        # does not starve claim wake and vice versa.
        self._claim_nudge: asyncio.Event | None = None
        # 8f: explicit init so _outlook_call never AttributeErrors if called
        # before _outlook_token. Previously created implicitly in _outlook_token.
        self._outlook_access_token: str | None = None

    def nudge(self) -> None:
        """Wake the coordinator immediately (approve/request_email_sync_now path)."""
        try:
            if self._nudge_event is not None and not self._nudge_event.is_set():
                self._nudge_event.set()
            if self._claim_nudge is not None and not self._claim_nudge.is_set():
                self._claim_nudge.set()
        except Exception:
            pass

    def ensure_nudge(self) -> asyncio.Event:
        if self._nudge_event is None:
            self._nudge_event = asyncio.Event()
        return self._nudge_event

    def ensure_claim_nudge(self) -> asyncio.Event:
        if self._claim_nudge is None:
            self._claim_nudge = asyncio.Event()
        return self._claim_nudge

    def nudge_claim(self) -> None:
        try:
            if self._claim_nudge is not None and not self._claim_nudge.is_set():
                self._claim_nudge.set()
        except Exception:
            pass

    def stop(self) -> None:
        self.stop_event.set()
        # Wake coordinator and claim loops if they are sleeping on nudge events
        try:
            if self._nudge_event is not None and not self._nudge_event.is_set():
                self._nudge_event.set()
            if self._claim_nudge is not None and not self._claim_nudge.is_set():
                self._claim_nudge.set()
        except Exception:
            pass

    async def run_sync_once(self) -> bool:
        claim = await self.repository.claim_due_sync(self.worker_id)
        if not claim:
            return await self.run_reconciliation_once()
        started_at = time.monotonic()
        try:
            totals = await self.discover(claim)
            if not await self.repository.complete_sync(claim, self.worker_id):
                logger.warning("Email sync completion lost lease provider=%s", claim.provider)
            self._log_sync_run(claim, started_at, totals=totals)
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
            await self.repository.fail_sync(claim, self.worker_id, exc)
            self._log_sync_run(claim, started_at, error_code=safe_error_code(exc))
        return True

    async def run_reconciliation_once(self) -> bool:
        claim = await self.repository.claim_due_reconciliation(self.worker_id)
        if not claim:
            return False
        started_at = time.monotonic()
        try:
            days = self.config.email_reconcile_weekly_days if claim.run_kind == "weekly_reconcile" else self.config.email_reconcile_daily_days
            totals = await self.reconcile(claim, days)
            await self.repository.complete_sync(claim, self.worker_id, reconciled=True)
            self._log_sync_run(claim, started_at, totals=totals)
        except Exception as exc:
            # 8e: record Graph failures during reconciliation too (most likely to hit throttling)
            if isinstance(exc, GraphHttpError):
                record_graph_failure(
                    self.client,
                    self.config,
                    integration_id=claim.integration_id,
                    operation="reconcile",
                    url=getattr(exc, "safe_url_template", "/me/mailFolders/{folder-id}/messages/delta"),
                    error=exc,
                    run_id=claim.run_id,
                )
            logger.warning("Email reconcile failed provider=%s code=%s", claim.provider, safe_error_code(exc))
            await self.repository.fail_sync(claim, self.worker_id, exc)
            self._log_sync_run(claim, started_at, error_code=safe_error_code(exc))
        return True

    def _log_sync_run(
        self,
        claim: SyncClaim,
        started_at: float,
        *,
        totals: dict[str, int] | None = None,
        error_code: str | None = None,
    ) -> None:
        """Emit one structured log line per completed sync run.

        Stable key/value shape so Render log search can answer "is ingestion
        moving" without a metrics backend. Never logs subjects, addresses,
        message ids or tokens — the existing safe-payload discipline in
        email_sync_health.py is the standard.
        """
        duration_ms = int((time.monotonic() - started_at) * 1000)
        totals = totals or {}
        logger.info(
            "ingestion_sync_run"
            " run_kind=%s provider=%s duration_ms=%d"
            " provider_ids_seen=%d items_inserted=%d items_existing=%d"
            " error_code=%s",
            claim.run_kind,
            claim.provider,
            duration_ms,
            int(totals.get("provider_ids_seen") or 0),
            int(totals.get("items_inserted") or 0),
            int(totals.get("items_existing") or 0),
            error_code or "",
        )

    async def discover(self, claim: SyncClaim) -> dict[str, int]:
        if claim.provider == "gmail":
            return await self._discover_gmail(claim)
        elif claim.provider == "outlook":
            return await self._discover_outlook(claim)
        else:
            raise ValueError(f"Unsupported email provider: {claim.provider}")

    def _integration(self, integration_id: str) -> dict[str, Any]:
        result = self.client.table("integrations").select("*").eq("id", integration_id).single().execute()
        return result.data

    async def _discover_gmail(self, claim: SyncClaim, *, lookback_days: int | None = None) -> dict[str, int]:
        totals = {"provider_ids_seen": 0, "items_inserted": 0, "items_existing": 0}
        integration = self._integration(claim.integration_id)
        credentials = get_gmail_credentials(self.client, self.config, user_id=claim.user_id)
        if not credentials:
            raise ProviderAuthenticationError("Gmail credentials are unavailable")
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
        # Inc1 payload: hourly folder refresh — skip listing/upsert inside interval
        _folders_due = True
        try:
            _state = self.client.table("email_sync_state").select("folders_refreshed_at").eq("integration_id", claim.integration_id).single().execute()
            _fr = (_state.data or {}).get("folders_refreshed_at")
            if _fr:
                from datetime import datetime, timezone
                _prev = datetime.fromisoformat(str(_fr).replace("Z", "+00:00"))
                _age = (datetime.now(timezone.utc) - _prev).total_seconds()
                if _age < self.config.email_folder_refresh_seconds:
                    _folders_due = False
        except Exception:
            _folders_due = True
        if _folders_due:
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
            try:
                self.client.table("email_sync_state").update({"folders_refreshed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}).eq("integration_id", claim.integration_id).execute()
            except Exception:
                pass
        cursor = integration.get("sync_cursor")
        # 6c: get_user_profile() was fetched unconditionally here, but
        # replacement_cursor is only used when there is no cursor (initial sync)
        # or when Gmail History expired and we must fall back to a bounded
        # listing. Defer to those branches: a 5-minute incremental poll on a
        # healthy cursor never needs the profile at all (one wasted Gmail call
        # per integration per poll, forever).
        # R4: heartbeat around long provider enumeration so a slow listing does
        # not outlive the 900s lease before the first upsert.
        replacement_cursor = None
        if lookback_days is not None or not cursor:
            await self.repository.require_heartbeat(claim.integration_id, self.worker_id, claim.lease_generation)
            replacement_cursor = get_user_profile(service).get("historyId")
            query = build_initial_sync_query(days=lookback_days or 14)
            identities = [row.get("id") for row in list_message_ids(service, query=query) if row.get("id")]
            await self.repository.require_heartbeat(claim.integration_id, self.worker_id, claim.lease_generation)
            next_cursor = None if lookback_days is not None else replacement_cursor
        else:
            try:
                await self.repository.require_heartbeat(claim.integration_id, self.worker_id, claim.lease_generation)
                identities, next_cursor = fetch_history_message_ids(service, cursor)
                await self.repository.require_heartbeat(claim.integration_id, self.worker_id, claim.lease_generation)
            except GmailHistoryExpiredError:
                # Capture the replacement history boundary before the bounded
                # listing so new mail arriving during reconciliation is not lost.
                await self.repository.require_heartbeat(claim.integration_id, self.worker_id, claim.lease_generation)
                replacement_cursor = get_user_profile(service).get("historyId")
                identities = [row.get("id") for row in list_message_ids(service, query=build_initial_sync_query()) if row.get("id")]
                await self.repository.require_heartbeat(claim.integration_id, self.worker_id, claim.lease_generation)
                next_cursor = None if lookback_days is not None else replacement_cursor

        # 6b: incremental polls are already O(delta) and are never bounded here.
        if lookback_days is not None:
            identities = await self._bound_reconcile_identities(claim, identities)

        # 6a: fetch metadata in Gmail batches (one HTTP request per 100
        # messages) instead of one ``get_message_metadata`` call per message.
        # Discovery already paid for one ``list_message_ids`` trip; this used
        # to add a second round-trip per message with no batching and no
        # concurrency — ~20k serial calls on a weekly reconciliation of a 20k
        # mailbox. Per-message 404s (message deleted between list and fetch)
        # are returned as {"_deleted": True} and become ``removed`` entries.
        metadata_by_id = get_messages_metadata_batch(service, identities)

        discovered: list[dict[str, Any]] = []
        for identity in identities:
            metadata = metadata_by_id.get(identity)
            if metadata is None or metadata.get("_deleted"):
                discovered.append({"provider_message_id": identity, "change_kind": "removed"})
                continue
            folder_ids = sorted(set(metadata.get("labelIds") or []))
            discovered.append({
                "provider_message_id": identity,
                "provider_folder_ids": folder_ids,
                "change_kind": "upsert" if _eligible_gmail_metadata(metadata, excluded) else "removed",
            })
            if len(discovered) >= 100:
                await self.repository.require_heartbeat(claim.integration_id, self.worker_id, claim.lease_generation)
                page = await self.repository.upsert_discovered(claim, discovered)
                _accumulate_page_totals(totals, page)
                discovered = []
        if discovered or next_cursor or lookback_days is not None:
            await self.repository.require_heartbeat(claim.integration_id, self.worker_id, claim.lease_generation)
            page = await self.repository.upsert_discovered(claim, discovered, cursor=next_cursor)
            _accumulate_page_totals(totals, page)
        return totals

    async def _bound_reconcile_identities(
        self, claim: SyncClaim, identities: list[str]
    ) -> list[str]:
        """Bound one Gmail reconcile pass by work, and make the bound resumable.

        A 90-day weekly reconciliation on a 20k-message mailbox used to list and
        fetch metadata for every message in the window inside a single 900s
        lease — roughly 100k Gmail quota units. When that tripped the per-user
        rate limit the entire pass failed and retried from the beginning, so a
        mailbox above the limit could never finish a reconcile at all.

        Two bounds fix that, in order:

        1. Drop identities already in ``email_ingestion_items``. Reconciliation
           exists to catch messages the incremental History path missed;
           re-fetching metadata for mail already discovered buys nothing. On a
           healthy mailbox this alone takes the pass to near-zero provider
           calls.
        2. Cap whatever remains at ``email_reconcile_max_identities``.

        The cap resumes because of step 1: identities processed this pass are
        committed by ``upsert_discovered`` before the lease ends, so the next
        pass filters them out and continues from where this one stopped. A
        plain ``identities[:max]`` would re-truncate the same prefix every pass
        and never reach the tail of the window.
        """
        known = await self.repository.known_provider_message_ids(
            claim.integration_id, identities
        )
        remaining = [identity for identity in identities if identity not in known]
        max_identities = self.config.email_reconcile_max_identities
        if max_identities > 0 and len(remaining) > max_identities:
            logger.info(
                "Gmail reconcile bounded integration=%s undiscovered=%d cap=%d (resumes next pass)",
                claim.integration_id,
                len(remaining),
                max_identities,
            )
            return remaining[:max_identities]
        return remaining

    def _outlook_token(self, user_id: str, *, force_refresh: bool = False) -> str:
        token = get_access_token(self.client, self.config, user_id, force_refresh=force_refresh)
        if not token:
            raise ProviderAuthenticationError("Outlook credentials are unavailable")
        self._outlook_access_token = token
        return token

    def _outlook_call(self, user_id: str, operation):
        """Run one Graph call, refreshing once if the access token has expired.

        Graph access tokens last about an hour while a mailbox pass over many
        folders — especially a 90-day weekly reconciliation — can run longer.
        Without this, a mid-pass 401 propagates as `provider_auth_expired`,
        which marks the integration expired and stops ingestion entirely until
        the user reconnects, even though the refresh token is perfectly valid.
        """
        if not self._outlook_access_token:
            raise RuntimeError("Outlook access token not initialized — call _outlook_token first")
        try:
            return operation(self._outlook_access_token)
        except GraphHttpError as exc:
            if exc.status_code != 401:
                raise
            logger.info("Outlook access token expired mid-run; refreshing once")
            return operation(self._outlook_token(user_id, force_refresh=True))

    async def _discover_outlook(self, claim: SyncClaim, *, lookback_days: int | None = None) -> dict[str, int]:
        totals = {"provider_ids_seen": 0, "items_inserted": 0, "items_existing": 0}
        await self.repository.require_heartbeat(claim.integration_id, self.worker_id, claim.lease_generation)
        self._outlook_token(claim.user_id)
        graph_context = GraphCallContext(
            client=self.client,
            config=self.config,
            integration_id=claim.integration_id,
            run_id=claim.run_id,
        )

        def list_folders(token: str):
            resolved = resolve_well_known_folder_ids(token, context=graph_context)
            return normalize_mail_folders(
                fetch_mail_folders(
                    token,
                    resolved_well_known_ids=resolved,
                    context=graph_context,
                )
            )

        # Inc1 payload: hourly folder refresh
        _folders_due = True
        try:
            _state = self.client.table("email_sync_state").select("folders_refreshed_at").eq("integration_id", claim.integration_id).single().execute()
            _fr = (_state.data or {}).get("folders_refreshed_at")
            if _fr:
                from datetime import datetime, timezone
                _prev = datetime.fromisoformat(str(_fr).replace("Z", "+00:00"))
                _age = (datetime.now(timezone.utc) - _prev).total_seconds()
                if _age < self.config.email_folder_refresh_seconds:
                    _folders_due = False
        except Exception:
            _folders_due = True
        if _folders_due:
            discovered = self._outlook_call(claim.user_id, list_folders)
            await self.repository.require_heartbeat(claim.integration_id, self.worker_id, claim.lease_generation)
            upsert_discovered_folders(
                self.client,
                user_id=claim.user_id,
                integration_id=claim.integration_id,
                provider="outlook",
                folders=discovered,
            )
            try:
                self.client.table("email_sync_state").update({"folders_refreshed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}).eq("integration_id", claim.integration_id).execute()
            except Exception:
                pass
        rows = (
            self.client.table("email_folders")
            .select("*")
            .eq("integration_id", claim.integration_id)
            .eq("provider", "outlook")
            .execute()
        )
        failures: list[BaseException] = []
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days or 14)
        # 6b deliberately does not bound the Outlook pass. The quota cliff it
        # addresses is Gmail-specific: Gmail discovery costs one extra metadata
        # round-trip *per message*, while Graph returns message metadata inline
        # with the folder listing, so an Outlook reconcile is O(folders), not
        # O(messages). Capping here would mean breaking out of this loop with
        # folders left unvisited — and `rows` has no ORDER BY, so which folders
        # get skipped is whatever order Postgres returns. That risks a folder
        # going unreconciled indefinitely to solve a cost problem Outlook does
        # not have. Per-message identity filtering is also unavailable here: a
        # message in two folders must be seen under both so upsert_discovered
        # can union its provider_folder_ids.
        for folder in rows.data or []:
            if not folder.get("is_included") or not folder.get("is_scannable", True):
                continue
            try:
                if lookback_days is not None:
                    changes = self._outlook_call(
                        claim.user_id,
                        lambda tok: fetch_folder_messages(
                            tok,
                            folder["provider_folder_id"],
                            since=since,
                            context=graph_context,
                        ),
                    )
                    cursor = None
                else:
                    changes, cursor = self._outlook_call(
                        claim.user_id,
                        lambda tok: fetch_message_changes(
                            tok,
                            folder.get("sync_cursor"),
                            folder_id=folder["provider_folder_id"],
                            since=since if not folder.get("sync_cursor") else None,
                            immutable_ids=True,
                            context=graph_context,
                        ),
                    )
                    if cursor == RESYNC_REQUIRED:
                        changes, cursor = self._outlook_call(
                            claim.user_id,
                            lambda tok: fetch_message_changes(
                                tok,
                                None,
                                folder_id=folder["provider_folder_id"],
                                since=since,
                                immutable_ids=True,
                                context=graph_context,
                            ),
                        )
                    if cursor == RESYNC_REQUIRED:
                        # A resync that itself needs a resync must not persist
                        # the sentinel as the folder's delta link; that would
                        # poison the cursor and every later run would send it
                        # to Graph as a URL.
                        raise GraphHttpError(410, "Outlook resync did not yield a delta link")
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
                    await self.repository.require_heartbeat(claim.integration_id, self.worker_id, claim.lease_generation)
                    page_totals = await self.repository.upsert_discovered(
                        claim,
                        items,
                        cursor=cursor if is_last else None,
                        folder_id=folder["id"] if cursor and is_last else None,
                    )
                    _accumulate_page_totals(totals, page_totals)
                if not pages and cursor:
                    # An empty delta page can still be the completed page that
                    # carries the new opaque delta link.
                    await self.repository.require_heartbeat(claim.integration_id, self.worker_id, claim.lease_generation)
                    page_totals = await self.repository.upsert_discovered(
                        claim, [], cursor=cursor, folder_id=folder["id"]
                    )
                    _accumulate_page_totals(totals, page_totals)
            except GraphHttpError as exc:
                if exc.status_code == 404:
                    self.client.table("email_folders").delete().eq("id", folder["id"]).execute()
                    continue
                logger.warning(
                    "Outlook folder %s discovery failed code=%s (%d failures so far)",
                    folder.get("provider_folder_id"),
                    safe_error_code(exc),
                    len(failures) + 1,
                )
                failures.append(exc)
            except Exception as exc:
                # 8d: log secondary failures, not just the first raised one
                logger.warning(
                    "Outlook folder %s discovery failed code=%s (%d failures so far)",
                    folder.get("provider_folder_id"),
                    safe_error_code(exc),
                    len(failures) + 1,
                )
                failures.append(exc)
        if failures:
            # 8d: log every failure, not just the first, before raising
            for idx, failure in enumerate(failures):
                logger.warning(
                    "Outlook discovery secondary failure %d/%d: %s",
                    idx + 1,
                    len(failures),
                    safe_error_code(failure),
                )
            logger.info(
                "Outlook discovery completed with %d failures; raising first (code=%s)",
                len(failures),
                safe_error_code(failures[0]),
            )
            raise failures[0]
        return totals

    async def reconcile(self, claim: SyncClaim, lookback_days: int) -> dict[str, int]:
        """Run cursorless reconciliation; normal cursor state is untouched."""
        if claim.provider == "gmail":
            return await self._discover_gmail(claim, lookback_days=lookback_days)
        elif claim.provider == "outlook":
            return await self._discover_outlook(claim, lookback_days=lookback_days)
        return {"provider_ids_seen": 0, "items_inserted": 0, "items_existing": 0}

    async def run_acquisition_once(self) -> bool:
        # Acquire the executor slot BEFORE claiming. Claiming first lets the
        # drain loop outrun the executors, and every claimed row holds a lease
        # that expires while it waits in the queue.
        if not await _try_acquire(self._acquisition_semaphore):
            return False
        try:
            item = await self.repository.claim_item(self.worker_id)
        except BaseException:
            self._acquisition_semaphore.release()
            raise
        if not item:
            self._acquisition_semaphore.release()
            return False

        task = asyncio.create_task(self._process_acquisition_item(item))
        self._acquisition_inflight.add(task)
        task.add_done_callback(self._acquisition_inflight.discard)
        task.add_done_callback(lambda _: self._acquisition_semaphore.release())
        return True

    async def _process_acquisition_item(self, item: dict[str, Any]) -> None:
        try:
            if item.get("change_kind") == "removed":
                await self.repository.remove_item(item["id"], self.worker_id)
                return
            email_id = await self.acquire_item(item)
            if not await self.repository.complete_item(item["id"], self.worker_id, email_id):
                logger.warning("Email acquisition completion lost lease")
        except (GraphHttpError, ProviderMessageMissingError) as exc:
            if getattr(exc, "status_code", None) == 404 or isinstance(exc, ProviderMessageMissingError):
                await self.repository.remove_item(item["id"], self.worker_id)
            else:
                await self.repository.fail_item(item["id"], self.worker_id, exc)
        except Exception as exc:
            # No failure is terminal on a code alone. The classifier inside
            # fail_item marks only ProviderPermanentError as non-retryable; any
            # other failure retries until max_attempts is exhausted server-side,
            # so a 401 resolved by reconnect never dead-letters mail on attempt #1.
            await self.repository.fail_item(item["id"], self.worker_id, exc)

    async def acquire_item(self, item: dict[str, Any]) -> str:
        provider = item["provider"]
        if provider == "gmail":
            credentials = get_gmail_credentials(self.client, self.config, user_id=item["user_id"])
            if not credentials:
                raise ProviderAuthenticationError("Gmail credentials are unavailable")
            # 8a: direct import, patch at use site
            # (selko.workers.email_ingestion.get_gmail_full_message)
            message = get_gmail_full_message(
                build_service(credentials), item["provider_message_id"]
            )
            parsed = parse_gmail_message(message)
            parsed["integration_id"] = item["integration_id"]
            parsed["provider_folder_ids"] = item.get("provider_folder_ids") or parsed.get("provider_folder_ids") or []
            calendar_payloads = gmail.extract_inline_calendar_parts(message)
            for calendar_attachment in extract_attachments(message):
                mime_type = (calendar_attachment.get("mime_type") or "").lower()
                filename = (calendar_attachment.get("filename") or "").lower()
                if mime_type == "text/calendar" or filename.endswith(".ics"):
                    calendar_payloads.append(
                        download_gmail_attachment(
                            build_service(credentials),
                            item["provider_message_id"],
                            calendar_attachment["attachment_id"],
                        )
                    )
            calendar_components = parse_calendar_components(calendar_payloads)
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
                raise ProviderAuthenticationError("Outlook credentials are unavailable")
            message = get_outlook_full_message(
                token,
                item["provider_message_id"],
                context=GraphCallContext(
                    client=self.client,
                    config=self.config,
                    integration_id=item["integration_id"],
                ),
            )
            parsed = parse_outlook_message(message)
            parsed["integration_id"] = item["integration_id"]
            parsed["provider_folder_ids"] = item.get("provider_folder_ids") or parsed.get("provider_folder_ids") or []
            calendar_components = parsed.pop("calendar_components", [])
            descriptors = [
                {
                    "provider_attachment_id": d.get("id"),
                    "filename": d.get("name"),
                    "mime_type": d.get("contentType"),
                    "size_bytes": d.get("size"),
                }
                for d in list_attachments(
                    token,
                    item["provider_message_id"],
                    context=GraphCallContext(
                        client=self.client,
                        config=self.config,
                        integration_id=item["integration_id"],
                    ),
                )
            ]
        else:
            raise ValueError(f"Unsupported email provider: {provider}")

        # Atomically commit the email upsert and its attachment descriptors in
        # one transaction so the SQL readiness gate (claim_unprocessed_email)
        # never observes an email row whose descriptors have not been written
        # yet. The old sequence (save_emails then N×(SELECT+INSERT)) left a
        # multi-round-trip window in which an LLM worker could claim the email
        # with zero attachment rows, causing silent flaky extraction.
        email_id = await self.repository.save_email_with_attachment_descriptors(
            item["user_id"], parsed, descriptors, calendar_components
        )
        return email_id

    async def run_attachment_once(self) -> bool:
        # C4: acquire the executor slot BEFORE claiming (same rule as
        # acquisition) so a claimed attachment never waits holding a lease.
        if not await _try_acquire(self._attachment_semaphore):
            return False
        try:
            attachment = await self.repository.claim_attachment(self.worker_id)
        except BaseException:
            self._attachment_semaphore.release()
            raise
        if not attachment:
            self._attachment_semaphore.release()
            return False

        task = asyncio.create_task(self._process_attachment_item(attachment))
        self._attachment_inflight.add(task)
        task.add_done_callback(self._attachment_inflight.discard)
        task.add_done_callback(lambda _: self._attachment_semaphore.release())
        return True

    async def _process_attachment_item(self, attachment: dict[str, Any]) -> None:
        try:
            status = await self.acquire_attachment(attachment)
            await self.repository.finish_attachment(attachment["id"], self.worker_id, status)
        except Exception as exc:
            terminal = attachment.get("attempts", 0) >= attachment.get("max_attempts", 8)
            await self.repository.finish_attachment(
                attachment["id"], self.worker_id,
                "dead_letter" if terminal else "retry", safe_error_code(exc),
            )

    async def acquire_attachment(self, attachment: dict[str, Any]) -> str:
        mime = str(attachment.get("mime_type") or "application/octet-stream").lower()
        if not (mime.startswith(SUPPORTED_ATTACHMENT_MIME_PREFIXES) or mime in SUPPORTED_ATTACHMENT_MIMES):
            return "unsupported"
        email = self.client.table("emails").select("user_id,email_provider,provider_message_id,integration_id").eq("id", attachment["email_id"]).single().execute().data
        if email["email_provider"] == "gmail":
            credentials = get_gmail_credentials(self.client, self.config, user_id=email["user_id"])
            if not credentials:
                raise ProviderAuthenticationError("Gmail credentials are unavailable")
            message = get_gmail_full_message(build_service(credentials), email["provider_message_id"])
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
                raise ProviderAuthenticationError("Outlook credentials are unavailable")
            descriptor = next(
                (
                    d
                    for d in list_attachments(
                        token,
                        email["provider_message_id"],
                        context=GraphCallContext(
                            client=self.client,
                            config=self.config,
                            integration_id=email["integration_id"],
                        ),
                    )
                    if d.get("id") == attachment["provider_attachment_id"]
                ),
                None,
            )
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
        # Ensure nudge event is bound to this loop
        nudge = self.ensure_nudge()
        while not self.stop_event.is_set():
            did_work = await self._guarded(self.run_sync_once)
            if did_work:
                continue
            # Idle: wait for tick, stop, or nudge
            tick = max(self.config.email_coordinator_tick_seconds, 1)
            # Race stop and nudge together so an approve wake doesn't stall shutdown
            try:
                # Wait for nudge with timeout = tick; stop_event is checked via outer loop
                await asyncio.wait_for(nudge.wait(), timeout=tick)
            except asyncio.TimeoutError:
                pass
            # Consume nudge edge; also break early if stop was requested
            if nudge.is_set():
                nudge.clear()
                if self.stop_event.is_set():
                    break
            # Also check stop_event without blocking (coordinator_loop previously
            # did `wait_for(stop_event.wait(), timeout=tick)`; now nudge and tick
            # share the timeout, and stop is handled by the outer while + explicit wake)
            if self.stop_event.is_set():
                break

    async def _guarded(self, run_once) -> bool:
        """Run one loop iteration so the loop can never be killed by a blip.

        ``claim_due_sync`` / ``claim_due_reconciliation`` / ``claim_item`` /
        ``claim_attachment`` are all called at the top of the ``run_*_once``
        bodies, *outside* their inner ``try``. Before this guard, a single
        transient Supabase error (a "Server disconnected without sending a
        response" mid-claim) propagated up through ``coordinator_loop`` /
        ``_claim_loop``, the task ended ``done()`` with an exception, and
        ``IngestionRuntime.stop()`` later gathered with ``return_exceptions=True``
        — silently swallowing the traceback. One attempt, loop dead forever.

        This mirrors ``WorkerPool._scheduler_loop``: catch every non-cancel
        exception, log it with a traceback, back off briefly, and return
        ``True`` so the iteration is treated as work (idle backoff does not
        compound on top of the error backoff).
        """
        try:
            return await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ingestion loop iteration failed; backing off")
            try:
                await asyncio.sleep(max(self.config.email_worker_error_backoff_seconds, 0.0))
            except asyncio.CancelledError:
                raise
            return True

    def idle_backoff(self, consecutive_idle: int) -> float:
        """Seconds to wait after `consecutive_idle` empty claims in a row.

        A flat one-second retry means every claim loop issues a request per
        second forever, which is the dominant cost of an otherwise idle
        deployment. Backing off geometrically keeps a busy queue responsive
        while an idle one settles to one request per worker per max interval.
        """
        base = max(self.config.email_worker_idle_base_seconds, 0.1)
        ceiling = max(self.config.email_worker_idle_max_seconds, base)
        return min(ceiling, base * (2 ** max(consecutive_idle - 1, 0)))

    async def _claim_loop(self, run_once, work_type: str) -> None:
        # R3: claim loop is nudge-aware — discovery wakes it in <100ms instead
        # of up to 30s backoff. Backoff remains as the floor when no nudge
        # arrives (single idle model, not dual). C3: when the pg listener is
        # live, a NOTIFY for this work type wakes the idle wait immediately;
        # the safety-poll backoff below remains the floor so a missed
        # notification costs latency, never work.
        self.ensure_claim_nudge()
        consecutive_idle = 0
        while not self.stop_event.is_set():
            if await self._guarded(run_once):
                consecutive_idle = 0
                continue
            consecutive_idle += 1
            timeout = self.idle_backoff(consecutive_idle)
            claim_nudge = self._claim_nudge
            try:
                waiters = [asyncio.create_task(claim_nudge.wait())]
                if self._work_listener is not None:
                    waiters.append(
                        asyncio.create_task(
                            self._work_listener.event_for(work_type).wait()
                        )
                    )
                else:
                    waiters.append(asyncio.create_task(self.stop_event.wait()))
                _, pending = await asyncio.wait(
                    waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                if claim_nudge.is_set():
                    claim_nudge.clear()
                    consecutive_idle = 0
                if self._work_listener is not None:
                    self._work_listener.event_for(work_type).clear()
            except asyncio.CancelledError:
                raise
        # C4.4: drain in-flight executor tasks before the loop reports done.
        inflight = (
            self._acquisition_inflight
            if work_type == "item_pending"
            else self._attachment_inflight
        )
        if inflight:
            await asyncio.wait(inflight, timeout=30)

    async def acquisition_loop(self) -> None:
        await self._claim_loop(self.run_acquisition_once, "item_pending")

    async def attachment_loop(self) -> None:
        await self._claim_loop(self.run_attachment_once, "attachment_pending")

    async def run(self) -> None:
        await asyncio.gather(self.coordinator_loop(), self.acquisition_loop(), self.attachment_loop())
