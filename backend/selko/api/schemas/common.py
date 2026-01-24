"""Common Pydantic schemas for API responses."""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


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
