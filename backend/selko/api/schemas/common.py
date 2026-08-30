"""Common Pydantic schemas and error helpers for API responses."""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ErrorCode:
    """Standardized error codes for API responses.

    Each constant is a short, machine-readable string that API clients can
    use for programmatic error handling.
    """

    # Authentication / authorization
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"

    # Resource not found
    NOT_FOUND = "NOT_FOUND"
    EMAIL_NOT_FOUND = "EMAIL_NOT_FOUND"
    EVENT_NOT_FOUND = "EVENT_NOT_FOUND"
    CALENDAR_NOT_FOUND = "CALENDAR_NOT_FOUND"

    # Credentials / integrations
    CREDENTIALS_EXPIRED = "CREDENTIALS_EXPIRED"
    CREDENTIALS_NOT_FOUND = "CREDENTIALS_NOT_FOUND"

    # Rate limiting
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    QUOTA_SERVICE_ERROR = "QUOTA_SERVICE_ERROR"

    # Database
    DATABASE_ERROR = "DATABASE_ERROR"

    # Sync
    SYNC_FAILED = "SYNC_FAILED"
    CALENDAR_DIVERGED = "CALENDAR_DIVERGED"

    # Gmail
    GMAIL_API_ERROR = "GMAIL_API_ERROR"

    # Request validation
    INVALID_REQUEST = "INVALID_REQUEST"

    # Processing
    PROCESSING_FAILED = "PROCESSING_FAILED"

    # OAuth
    OAUTH_FAILED = "OAUTH_FAILED"

    # Server
    SERVER_ERROR = "SERVER_ERROR"


def error_detail(code: str, message: str) -> dict[str, str]:
    """Build a standardized error detail dict for HTTPException responses.

    Args:
        code: Machine-readable error code (use ``ErrorCode`` constants).
        message: Human-readable description of the error.

    Returns:
        ``{"error": code, "detail": message}``
    """
    return {"error": code, "detail": message}


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    detail: str | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated list response."""

    items: list[T]
    total: int
    offset: int
    limit: int


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    build_sha: str | None = None
    #: Absolute UTC time this process started, ISO-8601.
    #:
    #: `resolution.uptime_seconds` is a duration, and a duration cannot tell you
    #: *which* process answered. Two consecutive probes of production once
    #: returned uptimes 3.19 days apart while Render reported a single instance,
    #: and there was no way to tell a second process from a bad counter. An
    #: absolute start time makes that distinction trivial: same value means the
    #: same process, and it can be compared directly against the deploy time.
    started_at: str | None = None
    resolution: dict[str, object] = {}


class HealthDbResponse(BaseModel):
    """Database health check response."""

    status: str
    database: str


class HealthIngestionTaskResponse(BaseModel):
    """Per-task state inside ``/health/ingestion``."""

    name: str
    alive: bool
    restarts: int
    last_exception_code: str | None = None


class HealthIngestionResponse(BaseModel):
    """/health/ingestion response.

    Safe codes only — never payloads, addresses, message ids or tokens. The
    state machine already records ``consecutive_failures``, dead-letter counts
    and run history; this surface finally reads them.
    """

    status: str  # "ok" | "degraded" | "down"
    background_processing_enabled: bool
    instance_id: str | None = None
    tasks: list[HealthIngestionTaskResponse] = []
    integrations_due: int | None = None
    oldest_next_poll_seconds: int | None = None
    leases_held: int | None = None
    items_pending: int | None = None
    items_dead_letter: int | None = None
    attachments_dead_letter: int | None = None
    open_incidents: int | None = None
    ready_emails: int | None = None
    processing_emails: int | None = None
    stale_processing_emails: int | None = None
    #: Pending rows the claim RPC will never take. Guaranteed impossible by
    #: emails_pending_is_claimable_check, so any non-zero value means that
    #: invariant has been violated. Actionable; degrades the rollup.
    unclaimable_pending: int | None = None
    #: Terminal failures written by fail_email_processing once retries are
    #: exhausted. These rows are permanent, so this is history rather than a
    #: current degradation and must not affect the rollup: counting it did,
    #: which made 'ok' unreachable forever once any email failed.
    failed_emails: int | None = None
    stale_sync_runs: int | None = None
    listener: dict | None = None


class EgressOperationResponse(BaseModel):
    """One (destination, operation) row of the outbound traffic meter."""

    destination: str
    operation: str
    calls: int
    bytes: int
    calls_per_minute: float


class HealthEgressResponse(BaseModel):
    """/health/egress response — where this instance's outbound bytes went.

    A platform bandwidth alert reports a total; it cannot say which destination
    or operation produced it. This surface attributes the traffic, which is what
    distinguishes constant coordination polling from real provider downloads.

    Counters are process-local and reset on restart, so ``projected_bytes_per_30d``
    is an extrapolation of the rate since start — useful for spotting a constant
    background leak, not a billing figure.

    Safe by construction: operation names are templates with query strings
    stripped, so no message ids, addresses, or tokens appear here.
    """

    uptime_seconds: float
    total_calls: int
    total_bytes: int
    calls_per_second: float
    bytes_per_hour: int
    projected_bytes_per_30d: int
    by_destination: dict[str, dict[str, int]] = {}
    top_operations: list[EgressOperationResponse] = []
    bytes_per_mailbox_per_day: int | None = None
    transport: str = "none"
