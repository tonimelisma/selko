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

from selko.config import Config
from selko.services.google_errors import (
    INSUFFICIENT_SCOPE_REASONS,
    RATE_LIMIT_REASONS,
)

logger = logging.getLogger(__name__)

MAX_ERROR_DETAIL = 500
MAX_PAGE_ITEMS = 100
# Provider message IDs per `in_` filter when testing which are already known.
# Small enough that the generated PostgREST URL stays well inside the usual 8KB
# request-line limit, and that each response stays under the default row cap.
KNOWN_ID_QUERY_CHUNK = 200


def _normalize_provider_page(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize provider identity fields before encoding the JSONB payload.

    The database contract stores provider message and folder identifiers as
    text.  Some provider/client adapters return UUID objects for identifiers
    that originated in a database row, so normalize those two boundary fields
    explicitly instead of letting ``json.dumps`` fail on a valid identity
    page.
    """
    page = []
    for item in items:
        normalized = dict(item)
        if normalized.get("provider_message_id") is not None:
            normalized["provider_message_id"] = str(normalized["provider_message_id"])
        if "provider_folder_ids" in normalized:
            normalized["provider_folder_ids"] = [
                str(folder_id) for folder_id in (normalized["provider_folder_ids"] or [])
            ]
        page.append(normalized)
    return page


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

    def __post_init__(self) -> None:
        """Keep database UUIDs out of JSON-bound service-role payloads.

        asyncpg returns PostgreSQL UUID columns as ``uuid.UUID`` instances,
        while the worker passes these IDs to PostgREST-backed folder and
        integration helpers. Normalize at the repository boundary so every
        downstream caller receives the declared string contract.
        """
        for field in ("integration_id", "user_id", "run_id"):
            value = getattr(self, field)
            if not isinstance(value, str):
                object.__setattr__(self, field, str(value))


class EmailIngestionRepository:
    """Small service-role repository around the v2 coordination RPCs.

    Every operation runs over the asyncpg session-pooler pool (port 5432) —
    there is exactly one implementation per operation, and no PostgREST twin.
    Cost ~100B vs 1690B per call.
    """

    def __init__(self, config: Config, pg_pool):
        self.config = config
        self.pg_pool = pg_pool

    async def claim_due_sync(self, worker_id: str) -> SyncClaim | None:
        try:
            row = await self.pg_pool.fetchrow(
                "SELECT * FROM public.claim_due_email_sync($1, $2)",
                worker_id, self.config.email_lease_seconds,
            )
        except Exception as exc:
            raise EmailIngestionError(f"Failed to claim due email sync: {exc}") from exc
        return SyncClaim(**dict(row)) if row else None

    async def claim_due_reconciliation(self, worker_id: str) -> SyncClaim | None:
        try:
            row = await self.pg_pool.fetchrow(
                "SELECT * FROM public.claim_due_email_reconciliation($1, $2)",
                worker_id, self.config.email_lease_seconds,
            )
        except Exception as exc:
            raise EmailIngestionError(f"Failed to claim due email reconciliation: {exc}") from exc
        return SyncClaim(**dict(row)) if row else None

    async def heartbeat_sync(self, integration_id: str, worker_id: str) -> bool:
        try:
            val = await self.pg_pool.fetchval(
                "SELECT public.heartbeat_email_sync($1, $2, $3)",
                integration_id, worker_id, self.config.email_lease_seconds,
            )
        except Exception as exc:
            raise EmailIngestionError(f"Failed to heartbeat email sync: {exc}") from exc
        return bool(val)

    async def require_heartbeat(self, integration_id: str, worker_id: str) -> None:
        if not await self.heartbeat_sync(integration_id, worker_id):
            raise LeaseLostError("email sync lease is no longer owned")

    async def complete_sync(self, claim: SyncClaim, worker_id: str, *, reconciled: bool = False) -> bool:
        try:
            val = await self.pg_pool.fetchval(
                "SELECT public.complete_email_sync($1, $2, $3, $4, $5)",
                claim.integration_id, claim.run_id, worker_id,
                self.config.email_poll_interval_seconds, reconciled,
            )
        except Exception as exc:
            raise EmailIngestionError(f"Failed to complete email sync: {exc}") from exc
        return bool(val)

    async def fail_sync(self, claim: SyncClaim, worker_id: str, exc: BaseException) -> bool:
        classification = classify_email_error(exc)
        try:
            val = await self.pg_pool.fetchval(
                "SELECT public.fail_email_sync($1, $2, $3, $4, $5, $6, $7, $8)",
                claim.integration_id, claim.run_id, worker_id,
                classification.code, safe_error_detail(exc),
                self.config.email_retry_base_seconds, self.config.email_retry_max_seconds,
                classification.auth_failure,
            )
        except Exception as e:
            raise EmailIngestionError(f"Failed to fail email sync: {e}") from e
        return bool(val)

    async def upsert_discovered(
        self,
        claim: SyncClaim,
        items: Iterable[dict[str, Any]],
        *,
        cursor: str | None = None,
        folder_id: str | None = None,
    ) -> dict[str, int]:
        """Persist one bounded provider page before exposing its cursor."""
        import json

        page = _normalize_provider_page(items)
        if len(page) > MAX_PAGE_ITEMS:
            raise ValueError(f"provider page exceeds {MAX_PAGE_ITEMS} identities")
        try:
            row = await self.pg_pool.fetchrow(
                "SELECT * FROM public.upsert_discovered_email_items($1, $2, $3::jsonb, $4, $5)",
                claim.integration_id, claim.run_id, json.dumps(page), cursor, folder_id,
            )
        except Exception as exc:
            raise EmailIngestionError(f"Failed to upsert discovered email items: {exc}") from exc
        return dict(row) if row else {"inserted_count": 0, "existing_count": 0, "provider_ids_seen": 0}

    async def known_provider_message_ids(
        self, integration_id: str, provider_message_ids: Iterable[str]
    ) -> set[str]:
        """Subset of ``provider_message_ids`` already discovered for this integration.

        Queried in chunks so a full reconcile window — tens of thousands of
        IDs — never materializes in one query plan or one response.
        """
        known: set[str] = set()
        ids = [pid for pid in provider_message_ids if pid]
        try:
            for start in range(0, len(ids), KNOWN_ID_QUERY_CHUNK):
                chunk = ids[start : start + KNOWN_ID_QUERY_CHUNK]
                rows = await self.pg_pool.fetch(
                    "SELECT provider_message_id FROM public.email_ingestion_items"
                    " WHERE integration_id = $1 AND provider_message_id = ANY($2::text[])",
                    integration_id, chunk,
                )
                known.update(row["provider_message_id"] for row in rows if row.get("provider_message_id"))
        except Exception as exc:
            raise EmailIngestionError(f"Failed to query known provider message ids: {exc}") from exc
        return known

    async def claim_item(self, worker_id: str) -> dict[str, Any] | None:
        """Claim one durable ingestion item, returning string UUIDs.

        asyncpg returns PG ``uuid`` columns as :class:`uuid.UUID`; callers that
        build a ``jsonb`` payload (e.g. ``save_email_with_attachment_descriptors``
        via :meth:`EmailIngestionWorker.acquire_item`) would otherwise fail at
        ``json.dumps`` with ``TypeError: Object of type UUID is not JSON
        serializable``. Normalization happens here at the repository boundary
        so every consumer receives the declared ``str`` contract.
        """
        try:
            row = await self.pg_pool.fetchrow(
                "SELECT * FROM public.claim_email_ingestion_item($1, $2)",
                worker_id, self.config.email_lease_seconds,
            )
        except Exception as exc:
            raise EmailIngestionError(f"Failed to claim email ingestion item: {exc}") from exc
        if row is None:
            return None
        from selko.services.pg import _normalize_pg_row

        return _normalize_pg_row(dict(row))

    async def complete_item(self, item_id: str, worker_id: str, email_id: str) -> bool:
        try:
            val = await self.pg_pool.fetchval(
                "SELECT public.complete_email_ingestion_item($1, $2, $3)",
                item_id, worker_id, email_id,
            )
        except Exception as exc:
            raise EmailIngestionError(f"Failed to complete email ingestion item: {exc}") from exc
        return bool(val)

    async def save_email_with_attachment_descriptors(
        self,
        user_id: str,
        email_payload: dict[str, Any],
        descriptors: Iterable[dict[str, Any]],
        calendar_components: Iterable[dict[str, Any]] | None = None,
    ) -> str:
        """Atomically upsert the email row, its attachment descriptors, and calendar components.

        One SQL call commits all writes in a single transaction so the
        readiness gate never observes an email row whose descriptors or
        components have not been written yet. R3 extends this with
        p_calendar_components.
        """
        import json

        try:
            email_id = await self.pg_pool.fetchval(
                "SELECT public.save_email_with_attachment_descriptors($1::uuid, $2::jsonb, $3::jsonb, $4::jsonb)",
                user_id, json.dumps(email_payload), json.dumps(list(descriptors)), json.dumps(list(calendar_components or [])),
            )
        except Exception as exc:
            raise EmailIngestionError(f"Failed to save email with attachment descriptors: {exc}") from exc
        if email_id is None:
            raise EmailIngestionError("email upsert returned no row")
        return str(email_id)

    async def fail_item(self, item_id: str, worker_id: str, exc: BaseException, *, terminal: bool | None = None) -> bool:
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
        try:
            val = await self.pg_pool.fetchval(
                "SELECT public.fail_email_ingestion_item($1, $2, $3, $4, $5, $6)",
                item_id, worker_id, classification.code,
                self.config.email_retry_base_seconds, self.config.email_retry_max_seconds,
                terminal,
            )
        except Exception as e:
            raise EmailIngestionError(f"Failed to fail email ingestion item: {e}") from e
        return bool(val)

    async def remove_item(self, item_id: str, worker_id: str) -> bool:
        try:
            row = await self.pg_pool.fetchval(
                "UPDATE public.email_ingestion_items"
                " SET acquisition_status = 'removed', lease_owner = NULL,"
                " lease_expires_at = NULL, completed_at = $3, updated_at = $3"
                " WHERE id = $1 AND lease_owner = $2 RETURNING id",
                item_id, worker_id, datetime.now(timezone.utc),
            )
        except Exception as exc:
            raise EmailIngestionError(f"Failed to remove email ingestion item: {exc}") from exc
        return row is not None

    async def claim_attachment(self, worker_id: str) -> dict[str, Any] | None:
        """Claim one pending attachment, returning string UUIDs.

        Same boundary as :meth:`claim_item` — defensive even though the current
        attachment path does not ``json.dumps`` the row. A future log or payload
        change must not reintroduce the class.
        """
        try:
            row = await self.pg_pool.fetchrow(
                "SELECT * FROM public.claim_email_attachment($1, $2)",
                worker_id, self.config.email_lease_seconds,
            )
        except Exception as exc:
            raise EmailIngestionError(f"Failed to claim email attachment: {exc}") from exc
        if row is None:
            return None
        from selko.services.pg import _normalize_pg_row

        return _normalize_pg_row(dict(row))

    async def finish_attachment(self, attachment_id: str, worker_id: str, status: str, error_code: str | None = None) -> bool:
        try:
            val = await self.pg_pool.fetchval(
                "SELECT public.finish_email_attachment($1, $2, $3, $4)",
                attachment_id, worker_id, status, error_code,
            )
        except Exception as exc:
            raise EmailIngestionError(f"Failed to finish email attachment: {exc}") from exc
        return bool(val)

    async def ensure_attachment_descriptors(
        self,
        email_id: str,
        user_id: str,
        descriptors: Iterable[dict[str, Any]],
    ) -> int:
        """Create pending attachment work without resetting stored rows."""
        created = 0
        try:
            for descriptor in descriptors:
                provider_id = descriptor.get("provider_attachment_id") or descriptor.get("attachment_id")
                if not provider_id:
                    continue
                existing = await self.pg_pool.fetchval(
                    "SELECT id FROM public.attachments"
                    " WHERE email_id = $1 AND provider_attachment_id = $2",
                    email_id, provider_id,
                )
                if existing:
                    continue
                await self.pg_pool.execute(
                    "INSERT INTO public.attachments"
                    " (user_id, email_id, provider_attachment_id, filename, mime_type,"
                    " size_bytes, ingestion_status)"
                    " VALUES ($1, $2, $3, $4, $5, $6, 'pending')",
                    user_id, email_id, provider_id,
                    descriptor.get("filename") or descriptor.get("name") or "unnamed",
                    descriptor.get("mime_type") or descriptor.get("contentType") or "application/octet-stream",
                    descriptor.get("size_bytes") or descriptor.get("size") or 0,
                )
                created += 1
        except Exception as exc:
            raise EmailIngestionError(f"Failed to ensure attachment descriptors: {exc}") from exc
        return created

    async def attachment_readiness(self, email_id: str) -> bool:
        """Mirror the SQL readiness gate for diagnostics and repair tooling."""
        try:
            rows = await self.pg_pool.fetch(
                "SELECT ingestion_status FROM public.attachments WHERE email_id = $1",
                email_id,
            )
        except Exception as exc:
            raise EmailIngestionError(f"Failed to check attachment readiness: {exc}") from exc
        return all(
            row.get("ingestion_status") in {"stored", "unsupported", "dead_letter"}
            for row in rows
        )
