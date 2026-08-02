"""Durable state and retry boundaries for polling email ingestion v2.

Provider adapters use this module as the database contract. Discovery writes
immutable provider identities first; acquisition and attachment workers then
claim those rows independently. The service deliberately keeps provider
payloads out of logs and incident summaries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from supabase import Client

from selko.config import Config

logger = logging.getLogger(__name__)

MAX_ERROR_DETAIL = 500
MAX_PAGE_ITEMS = 100


class EmailIngestionError(Exception):
    """Base error for durable ingestion operations."""


class LeaseLostError(EmailIngestionError):
    """Raised when a worker no longer owns its integration lease."""


class ProviderAuthenticationError(EmailIngestionError):
    """Raised when provider credentials cannot be used."""


class ProviderMessageMissingError(EmailIngestionError):
    """Raised when a discovered provider message was deleted before acquire."""


@dataclass(frozen=True)
class SyncClaim:
    integration_id: str
    user_id: str
    provider: str
    run_id: str
    run_kind: str
    lease_expires_at: str | None = None


def _rpc_data(result: Any) -> list[dict[str, Any]]:
    data = getattr(result, "data", None)
    if data is None:
        return []
    if isinstance(data, dict):
        return [data]
    return list(data)


def safe_error_code(exc: BaseException) -> str:
    """Map arbitrary provider/database exceptions to stable safe codes."""
    if isinstance(exc, ProviderAuthenticationError):
        return "provider_auth_expired"
    if isinstance(exc, ProviderMessageMissingError):
        return "provider_message_missing"
    status = getattr(exc, "status_code", None)
    if status == 429:
        return "provider_rate_limited"
    if status in (401, 403):
        return "provider_auth_expired"
    text = str(exc).lower()
    if "timeout" in text or "connection" in text or "temporarily" in text:
        return "provider_transient"
    if "parse" in text or "invalid" in text:
        return "parse_invalid"
    if "postgrest" in text or "supabase" in text or "database" in text:
        return "database_transient"
    return "unknown"


def safe_error_detail(exc: BaseException) -> str:
    """Return a short redacted detail suitable for service-only diagnostics."""
    text = " ".join(str(exc).split())
    for sensitive in ("authorization", "bearer", "access_token", "refresh_token"):
        if sensitive in text.lower():
            return "provider operation failed"
    return text[:MAX_ERROR_DETAIL]


class EmailIngestionRepository:
    """Small service-role repository around the v2 coordination RPCs."""

    def __init__(self, client: Client, config: Config):
        self.client = client
        self.config = config

    def claim_due_sync(self, worker_id: str) -> SyncClaim | None:
        result = self.client.rpc(
            "claim_due_email_sync",
            {"p_worker_id": worker_id, "p_lease_seconds": self.config.email_lease_seconds},
        ).execute()
        rows = _rpc_data(result)
        return SyncClaim(**rows[0]) if rows else None

    def claim_due_reconciliation(self, worker_id: str) -> SyncClaim | None:
        result = self.client.rpc(
            "claim_due_email_reconciliation",
            {"p_worker_id": worker_id, "p_lease_seconds": self.config.email_lease_seconds},
        ).execute()
        rows = _rpc_data(result)
        return SyncClaim(**rows[0]) if rows else None

    def heartbeat_sync(self, integration_id: str, worker_id: str) -> bool:
        result = self.client.rpc(
            "heartbeat_email_sync",
            {
                "p_integration_id": integration_id,
                "p_worker_id": worker_id,
                "p_lease_seconds": self.config.email_lease_seconds,
            },
        ).execute()
        return bool(getattr(result, "data", False))

    def require_heartbeat(self, integration_id: str, worker_id: str) -> None:
        if not self.heartbeat_sync(integration_id, worker_id):
            raise LeaseLostError("email sync lease is no longer owned")

    def complete_sync(self, claim: SyncClaim, worker_id: str, *, reconciled: bool = False) -> bool:
        result = self.client.rpc(
            "complete_email_sync",
            {
                "p_integration_id": claim.integration_id,
                "p_run_id": claim.run_id,
                "p_worker_id": worker_id,
                "p_poll_interval_seconds": self.config.email_poll_interval_seconds,
                "p_reconciled": reconciled,
            },
        ).execute()
        return bool(getattr(result, "data", False))

    def fail_sync(self, claim: SyncClaim, worker_id: str, exc: BaseException) -> bool:
        code = safe_error_code(exc)
        result = self.client.rpc(
            "fail_email_sync",
            {
                "p_integration_id": claim.integration_id,
                "p_run_id": claim.run_id,
                "p_worker_id": worker_id,
                "p_error_code": code,
                "p_error_detail": safe_error_detail(exc),
                "p_retry_base_seconds": self.config.email_retry_base_seconds,
                "p_retry_max_seconds": self.config.email_retry_max_seconds,
                "p_auth_failure": code == "provider_auth_expired",
            },
        ).execute()
        return bool(getattr(result, "data", False))

    def upsert_discovered(
        self,
        claim: SyncClaim,
        items: Iterable[dict[str, Any]],
        *,
        cursor: str | None = None,
        folder_id: str | None = None,
    ) -> dict[str, int]:
        """Persist one bounded provider page before exposing its cursor."""
        page = list(items)
        if len(page) > MAX_PAGE_ITEMS:
            raise ValueError(f"provider page exceeds {MAX_PAGE_ITEMS} identities")
        result = self.client.rpc(
            "upsert_discovered_email_items",
            {
                "p_integration_id": claim.integration_id,
                "p_run_id": claim.run_id,
                "p_items": page,
                "p_cursor": cursor,
                "p_folder_id": folder_id,
            },
        ).execute()
        row = _rpc_data(result)
        return row[0] if row else {"inserted_count": 0, "existing_count": 0, "provider_ids_seen": 0}

    def claim_item(self, worker_id: str) -> dict[str, Any] | None:
        result = self.client.rpc(
            "claim_email_ingestion_item",
            {"p_worker_id": worker_id, "p_lease_seconds": self.config.email_lease_seconds},
        ).execute()
        rows = _rpc_data(result)
        return rows[0] if rows else None

    def complete_item(self, item_id: str, worker_id: str, email_id: str) -> bool:
        result = self.client.rpc(
            "complete_email_ingestion_item",
            {"p_item_id": item_id, "p_worker_id": worker_id, "p_email_id": email_id},
        ).execute()
        return bool(getattr(result, "data", False))

    def fail_item(self, item_id: str, worker_id: str, exc: BaseException, *, terminal: bool = False) -> bool:
        result = self.client.rpc(
            "fail_email_ingestion_item",
            {
                "p_item_id": item_id,
                "p_worker_id": worker_id,
                "p_error_code": safe_error_code(exc),
                "p_retry_base_seconds": self.config.email_retry_base_seconds,
                "p_retry_max_seconds": self.config.email_retry_max_seconds,
                "p_terminal": terminal,
            },
        ).execute()
        return bool(getattr(result, "data", False))

    def remove_item(self, item_id: str, worker_id: str) -> bool:
        result = (
            self.client.table("email_ingestion_items")
            .update({
                "acquisition_status": "removed",
                "lease_owner": None,
                "lease_expires_at": None,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", item_id)
            .eq("lease_owner", worker_id)
            .execute()
        )
        return bool(getattr(result, "data", None))

    def claim_attachment(self, worker_id: str) -> dict[str, Any] | None:
        result = self.client.rpc(
            "claim_email_attachment",
            {"p_worker_id": worker_id, "p_lease_seconds": self.config.email_lease_seconds},
        ).execute()
        rows = _rpc_data(result)
        return rows[0] if rows else None

    def finish_attachment(self, attachment_id: str, worker_id: str, status: str, error_code: str | None = None) -> bool:
        result = self.client.rpc(
            "finish_email_attachment",
            {
                "p_attachment_id": attachment_id,
                "p_worker_id": worker_id,
                "p_status": status,
                "p_error_code": error_code,
            },
        ).execute()
        return bool(getattr(result, "data", False))

    def ensure_attachment_descriptors(
        self,
        email_id: str,
        user_id: str,
        descriptors: Iterable[dict[str, Any]],
    ) -> int:
        """Create pending attachment work without resetting stored rows."""
        created = 0
        for descriptor in descriptors:
            provider_id = descriptor.get("provider_attachment_id") or descriptor.get("attachment_id")
            if not provider_id:
                continue
            existing = (
                self.client.table("attachments")
                .select("id")
                .eq("email_id", email_id)
                .eq("provider_attachment_id", provider_id)
                .maybe_single()
                .execute()
            )
            if getattr(existing, "data", None):
                continue
            self.client.table("attachments").insert({
                "user_id": user_id,
                "email_id": email_id,
                "provider_attachment_id": provider_id,
                "filename": descriptor.get("filename") or descriptor.get("name") or "unnamed",
                "mime_type": descriptor.get("mime_type") or descriptor.get("contentType") or "application/octet-stream",
                "size_bytes": descriptor.get("size_bytes") or descriptor.get("size") or 0,
                "ingestion_status": "pending",
            }).execute()
            created += 1
        return created

    def attachment_readiness(self, email_id: str) -> bool:
        """Mirror the SQL readiness gate for diagnostics and repair tooling."""
        result = self.client.table("attachments").select("ingestion_status").eq("email_id", email_id).execute()
        return all(row.get("ingestion_status") in {"stored", "unsupported", "dead_letter"} for row in (result.data or []))
