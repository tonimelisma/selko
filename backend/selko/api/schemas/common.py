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
