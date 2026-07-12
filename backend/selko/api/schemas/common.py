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
