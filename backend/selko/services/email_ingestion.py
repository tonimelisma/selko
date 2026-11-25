"""Durable state and retry boundaries for polling email ingestion v2.

Provider adapters use this module as the database contract. Discovery writes
immutable provider identities first; acquisition and attachment workers then
claim those rows independently. The service deliberately keeps provider
payloads out of logs and incident summaries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable

from selko.config import Config
from selko.db import attachments as db_attachments
from selko.db import email_sync
from selko.db import emails as db_emails
from selko.db.errors import DbBusy
from selko.services.google_errors import (
    INSUFFICIENT_SCOPE_REASONS,
    RATE_LIMIT_REASONS,
)

logger = logging.getLogger(__name__)

MAX_ERROR_DETAIL = 500
MAX_PAGE_ITEMS = 100
# Provider message IDs per query when testing which are already known; bounds
# the memory of one query over a full reconcile window.
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


class ExecutorTimeoutError(EmailIngestionError):
    """Raised when an executor exceeded its wall-clock bound.

    An unbounded executor does not merely delay one row: it holds its
    semaphore permit for as long as it runs. Executor width is 2 by default,
    so two never-returning items stopped acquisition permanently and
    silently — see ``EmailIngestionWorker._process_acquisition_item``. This
    is retryable: a bound that fired tells us nothing about the payload.
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
    """True for transport-level failures: a locked database or a provider disconnect.

    These retry — a disconnect is not a provider auth problem and not a parse
    problem. Kept structural (type-based), never substring-based. A database
    that stayed locked past ``busy_timeout`` is the one transient database
    failure SQLite has.
    """
    if isinstance(exc, DbBusy):
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
    # Distinct from the ``unknown`` fallback on purpose: a stalled executor is
    # the one failure mode whose symptom is the *absence* of attempts, so it
    # needs a code you can grep for once the rows start moving again.
    if isinstance(exc, ExecutorTimeoutError):
        return EmailErrorClassification(
            code="executor_timeout", retryable=True, auth_failure=False
        )
    # Lazy import for the same reason as GmailAuthError above: attachments is
    # imported by the workers that also import this module.
    try:
        from selko.services.attachments import AttachmentTypeRejected
    except Exception:  # pragma: no cover - defensive; always importable
        AttachmentTypeRejected = ()  # type: ignore[assignment]
    # Not retryable: the bucket's answer is a property of the content type, so
    # every further attempt reaches the same 415. The caller finishes the row
    # as `unsupported` rather than letting it reach dead_letter, which nothing
    # clears and which assert-health.sh calls never acceptable.
    if isinstance(exc, AttachmentTypeRejected):  # type: ignore[arg-type]
        return EmailErrorClassification(
            code="attachment_type_rejected", retryable=False, auth_failure=False
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
    lease_generation: int = 0
    lease_expires_at: str | None = None

    def __post_init__(self) -> None:
        """Keep every id a string: callers may pass ``uuid.UUID`` objects."""
        for field in ("integration_id", "user_id", "run_id"):
            value = getattr(self, field)
            if not isinstance(value, str):
                object.__setattr__(self, field, str(value))


class EmailIngestionRepository:
    """Service-wide repository around the v2 coordination functions.

    Every operation is one `selko.db.email_sync`/`emails`/`attachments`
    function run off the event loop (``Database.run``): one implementation per
    operation. ``pg_pool`` keeps its historical name; it is the process
    `selko.db.connection.Database`.
    """

    def __init__(self, config: Config, pg_pool):
        self.config = config
        self.pg_pool = pg_pool

    async def _call(self, what: str, fn, *args: Any) -> Any:
        try:
            return await self.pg_pool.run(fn, self.pg_pool, *args)
        except Exception as exc:
            raise EmailIngestionError(f"Failed to {what}: {exc}") from exc

    async def claim_due_sync(self, worker_id: str) -> SyncClaim | None:
        row = await self._call(
            "claim due email sync", email_sync.claim_due_email_sync,
            worker_id, self.config.email_lease_seconds,
        )
        return SyncClaim(**row) if row else None

    async def claim_due_reconciliation(self, worker_id: str) -> SyncClaim | None:
        row = await self._call(
            "claim due email reconciliation", email_sync.claim_due_email_reconciliation,
            worker_id, self.config.email_lease_seconds,
        )
        return SyncClaim(**row) if row else None

    async def heartbeat_sync(self, integration_id: str, worker_id: str, generation: int) -> bool:
        return bool(await self._call(
            "heartbeat email sync", email_sync.heartbeat_email_sync,
            integration_id, worker_id, generation, self.config.email_lease_seconds,
        ))

    async def require_heartbeat(self, integration_id: str, worker_id: str, generation: int) -> None:
        if not await self.heartbeat_sync(integration_id, worker_id, generation):
            raise LeaseLostError("email sync lease is no longer owned")

    async def complete_sync(self, claim: SyncClaim, worker_id: str, *, reconciled: bool = False) -> bool:
        return bool(await self._call(
            "complete email sync", email_sync.complete_email_sync,
            claim.integration_id, claim.run_id, worker_id, claim.lease_generation,
            self.config.email_poll_interval_seconds, reconciled,
        ))

    async def fail_sync(self, claim: SyncClaim, worker_id: str, exc: BaseException) -> bool:
        classification = classify_email_error(exc)
        return bool(await self._call(
            "fail email sync", email_sync.fail_email_sync,
            claim.integration_id, claim.run_id, worker_id, claim.lease_generation,
            classification.code, safe_error_detail(exc),
            self.config.email_retry_base_seconds, self.config.email_retry_max_seconds,
            classification.auth_failure,
        ))

    async def upsert_discovered(
        self,
        claim: SyncClaim,
        items: Iterable[dict[str, Any]],
        *,
        cursor: str | None = None,
        folder_id: str | None = None,
    ) -> dict[str, int]:
        """Persist one bounded provider page before exposing its cursor."""
        page = _normalize_provider_page(items)
        if len(page) > MAX_PAGE_ITEMS:
            raise ValueError(f"provider page exceeds {MAX_PAGE_ITEMS} identities")
        row = await self._call(
            "upsert discovered email items", email_sync.upsert_discovered_email_items,
            claim.integration_id, claim.run_id, page, cursor, folder_id,
        )
        return dict(row) if row else {"inserted_count": 0, "existing_count": 0, "provider_ids_seen": 0}

    async def known_provider_message_ids(
        self, integration_id: str, provider_message_ids: Iterable[str]
    ) -> set[str]:
        """Subset of ``provider_message_ids`` already discovered for this integration.

        Queried in chunks so a full reconcile window — tens of thousands of
        IDs — never materializes in one query.
        """
        return await self._call(
            "query known provider message ids", email_sync.known_provider_message_ids,
            integration_id, list(provider_message_ids), KNOWN_ID_QUERY_CHUNK,
        )

    async def claim_item(self, worker_id: str) -> dict[str, Any] | None:
        """Claim one durable ingestion item (ids are text)."""
        return await self._call(
            "claim email ingestion item", email_sync.claim_email_ingestion_item,
            worker_id, self.config.email_lease_seconds,
        )

    async def complete_item(self, item_id: str, worker_id: str, email_id: str) -> bool:
        return bool(await self._call(
            "complete email ingestion item", email_sync.complete_email_ingestion_item,
            item_id, worker_id, email_id,
        ))

    async def save_email_with_attachment_descriptors(
        self,
        user_id: str,
        email_payload: dict[str, Any],
        descriptors: Iterable[dict[str, Any]],
        calendar_components: Iterable[dict[str, Any]] = (),
    ) -> str:
        """Atomically upsert the email row and its attachment descriptors.

        One transaction commits all writes, so the readiness gate never
        observes an email row whose descriptors have not been written yet.
        """
        email_id = await self._call(
            "save email with attachment descriptors",
            db_emails.save_email_with_attachment_descriptors,
            user_id, email_payload, list(descriptors), list(calendar_components),
        )
        if email_id is None:
            raise EmailIngestionError("email upsert returned no row")
        return str(email_id)

    async def fail_item(self, item_id: str, worker_id: str, exc: BaseException, *, terminal: bool | None = None) -> bool:
        """Record an acquisition failure.

        ``terminal`` defaults to the classifier's ``retryable`` flag: only
        genuinely permanent failures (``ProviderPermanentError``) are terminal
        on the first attempt. Every other failure retries until ``max_attempts``
        is exhausted, so a transient blip — including a 401 that will be
        resolved by reconnect — never dead-letters mail on attempt #1.
        """
        classification = classify_email_error(exc)
        if terminal is None:
            terminal = not classification.retryable
        return bool(await self._call(
            "fail email ingestion item", email_sync.fail_email_ingestion_item,
            item_id, worker_id, classification.code,
            self.config.email_retry_base_seconds, self.config.email_retry_max_seconds,
            terminal,
        ))

    async def remove_item(self, item_id: str, worker_id: str) -> bool:
        return bool(await self._call(
            "remove email ingestion item", email_sync.remove_ingestion_item, item_id, worker_id,
        ))

    async def claim_attachment(self, worker_id: str) -> dict[str, Any] | None:
        """Claim one pending attachment (ids are text)."""
        return await self._call(
            "claim email attachment", db_attachments.claim_email_attachment,
            worker_id, self.config.email_lease_seconds,
        )

    async def finish_attachment(self, attachment_id: str, worker_id: str, status: str, error_code: str | None = None) -> bool:
        return bool(await self._call(
            "finish email attachment", db_attachments.finish_email_attachment,
            attachment_id, worker_id, status, error_code,
        ))
