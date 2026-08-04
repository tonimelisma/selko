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

from postgrest.exceptions import APIError as PostgrestAPIError
from supabase import Client

from selko.config import Config
from selko.services.google_errors import (
    INSUFFICIENT_SCOPE_REASONS,
    RATE_LIMIT_REASONS,
)

logger = logging.getLogger(__name__)

MAX_ERROR_DETAIL = 500
MAX_PAGE_ITEMS = 100


@dataclass(frozen=True)
class EmailErrorClassification:
    """Typed outcome of classifying an email ingestion failure.

    Branch on ``code`` and ``retryable``/``auth_failure`` — never on
    ``str(exc)``. ``retryable=False`` is reserved for genuinely permanent
    failures (``ProviderPermanentError``); everything else retries and only
    dead-letters by exhausting ``max_attempts`` server-side.
    """

    code: str
    retryable: bool
    auth_failure: bool


class EmailIngestionError(Exception):
    """Base error for durable ingestion operations."""


class LeaseLostError(EmailIngestionError):
    """Raised when a worker no longer owns its integration lease."""


class ProviderAuthenticationError(EmailIngestionError):
    """Raised when provider credentials cannot be used."""


class ProviderMessageMissingError(EmailIngestionError):
    """Raised when a discovered provider message was deleted before acquire."""


class ProviderPermanentError(EmailIngestionError):
    """Raised when a payload is genuinely unparseable and must not retry.

    This is the only path that dead-letters an item before ``max_attempts``.
    Parsers raise it deliberately; nothing infers permanence from a message.
    """


# Microsoft Graph error codes that mean throttle (retry) rather than auth.
_GRAPH_RATE_LIMIT_CODES = {"TooManyRequests", "Throttled"}
# Microsoft Graph error codes that mean scope/permission missing (auth).
_GRAPH_INSUFFICIENT_SCOPE_CODES = {
    "AuthorizationRequestDenied",
    "ErrorAccessDenied",
    "InsufficientScope",
}


def _graph_reason(exc: BaseException) -> str | None:
    """Best-effort extraction of a Graph structured reason (the ``code``)."""
    code = getattr(exc, "graph_error_code", None)
    return code if isinstance(code, str) and code else None


def _is_transport_exception(exc: BaseException) -> bool:
    """True for httpx/requests/postgrest transport-level failures.

    These retry — a disconnect is not a provider auth problem and not a parse
    problem. Kept structural (type-based), never substring-based.
    """
    if isinstance(exc, PostgrestAPIError):
        return True
    # GraphRequestError is created for transport failures with status_code None.
    status = getattr(exc, "status_code", None)
    failure_class = getattr(exc, "failure_class", None)
    if status is None and failure_class == "transport":
        return True
    return False


def classify_email_error(exc: BaseException) -> EmailErrorClassification:
    """Map arbitrary provider/database exceptions to a typed, stable classifier.

    This is the single place that interprets provider error shapes for the
    durable email ingestion path. Callers (``fail_item``, ``fail_sync``, the
    attachment loop) must branch on the returned ``code``/flags, never on
    ``str(exc)``.
    """
    # Typed auth (Gmail refresh revoked, missing-credential path, Graph 401).
    if isinstance(exc, ProviderAuthenticationError):
        return EmailErrorClassification(
            code="provider_auth_expired", retryable=True, auth_failure=True
        )
    # Import lazily to avoid a circular import (gmail imports from integrations;
    # this module only type-checks the subclass at classification time).
    try:
        from selko.services.gmail import GmailAuthError
    except Exception:  # pragma: no cover - defensive; gmail always importable
        GmailAuthError = ()  # type: ignore[assignment]
    if isinstance(exc, GmailAuthError):  # type: ignore[arg-type]
        return EmailErrorClassification(
            code="provider_auth_expired", retryable=True, auth_failure=True
        )
    if isinstance(exc, ProviderPermanentError):
        return EmailErrorClassification(
            code="provider_permanent", retryable=False, auth_failure=False
        )
    if isinstance(exc, ProviderMessageMissingError):
        # Removed by the caller, not failed-and-retried; keep a stable code.
        return EmailErrorClassification(
            code="provider_message_missing", retryable=True, auth_failure=False
        )

    status = getattr(exc, "status_code", None)
    if status is not None:
        reason = getattr(exc, "reason", None) or _graph_reason(exc)
        if status == 429 or (status == 403 and (
            reason in RATE_LIMIT_REASONS or reason in _GRAPH_RATE_LIMIT_CODES
        )):
            return EmailErrorClassification(
                code="provider_rate_limited", retryable=True, auth_failure=False
            )
        if status == 401 or (status == 403 and (
            reason in INSUFFICIENT_SCOPE_REASONS
            or reason in _GRAPH_INSUFFICIENT_SCOPE_CODES
        )):
            return EmailErrorClassification(
                code="provider_auth_expired", retryable=True, auth_failure=True
            )
        if status == 403:
            return EmailErrorClassification(
                code="provider_forbidden", retryable=True, auth_failure=False
            )
        if status in (500, 502, 503, 504):
            return EmailErrorClassification(
                code="provider_transient", retryable=True, auth_failure=False
            )
        if status == 404:
            return EmailErrorClassification(
                code="provider_not_found", retryable=True, auth_failure=False
            )

    if _is_transport_exception(exc):
        return EmailErrorClassification(
            code="database_transient", retryable=True, auth_failure=False
        )
    return EmailErrorClassification(
        code="unknown", retryable=True, auth_failure=False
    )


def safe_error_code(exc: BaseException) -> str:
    """Stable safe code string for an exception (see ``classify_email_error``)."""
    return classify_email_error(exc).code


def safe_error_detail(exc: BaseException) -> str:
    """Return a short redacted detail suitable for service-only diagnostics."""
    text = " ".join(str(exc).split())
    for sensitive in ("authorization", "bearer", "access_token", "refresh_token"):
        if sensitive in text.lower():
            return "provider operation failed"
    return text[:MAX_ERROR_DETAIL]


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
        classification = classify_email_error(exc)
        result = self.client.rpc(
            "fail_email_sync",
            {
                "p_integration_id": claim.integration_id,
                "p_run_id": claim.run_id,
                "p_worker_id": worker_id,
                "p_error_code": classification.code,
                "p_error_detail": safe_error_detail(exc),
                "p_retry_base_seconds": self.config.email_retry_base_seconds,
                "p_retry_max_seconds": self.config.email_retry_max_seconds,
                "p_auth_failure": classification.auth_failure,
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

    def save_email_with_attachment_descriptors(
        self,
        user_id: str,
        email_payload: dict[str, Any],
        descriptors: Iterable[dict[str, Any]],
    ) -> str:
        """Atomically upsert the email row and its attachment descriptors.

        One RPC commits both writes in a single transaction so the SQL
        readiness gate (``claim_unprocessed_email``) never observes an email
        row whose attachment descriptors have not been written yet — the race
        that let an LLM worker claim an email before its attachment rows
        existed, causing silent flaky extraction. Replaces the previous
        ``save_emails`` + N×(SELECT+INSERT) sequence in ``acquire_item``.
        """
        result = self.client.rpc(
            "save_email_with_attachment_descriptors",
            {
                "p_user_id": str(user_id),
                "p_email": email_payload,
                "p_descriptors": list(descriptors),
            },
        ).execute()
        data = getattr(result, "data", None)
        # PostgREST returns a scalar-RETURNS-uuid function call as the scalar
        # directly; guard both that and a row-list shape.
        if data is None:
            raise RuntimeError("email upsert returned no row")
        if isinstance(data, list):
            if not data:
                raise RuntimeError("email upsert returned no row")
            row = data[0]
            return row["id"] if isinstance(row, dict) else str(row)
        return str(data)

    def fail_item(self, item_id: str, worker_id: str, exc: BaseException, *, terminal: bool | None = None) -> bool:
        """Record an acquisition failure.

        ``terminal`` defaults to the classifier's ``retryable`` flag: only
        genuinely permanent failures (``ProviderPermanentError``) are terminal
        on the first attempt. Every other failure retries until ``max_attempts``
        is exhausted server-side, so a transient blip — including a 401 that
        will be resolved by reconnect — never dead-letters mail on attempt #1.
        """
        classification = classify_email_error(exc)
        if terminal is None:
            terminal = not classification.retryable
        result = self.client.rpc(
            "fail_email_ingestion_item",
            {
                "p_item_id": item_id,
                "p_worker_id": worker_id,
                "p_error_code": classification.code,
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
