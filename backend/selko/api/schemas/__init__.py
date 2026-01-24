"""Pydantic schemas for API responses."""

from selko.api.schemas.common import ErrorResponse, PaginatedResponse
from selko.api.schemas.emails import EmailResponse
from selko.api.schemas.integrations import IntegrationResponse

__all__ = [
    "ErrorResponse",
    "PaginatedResponse",
    "EmailResponse",
    "IntegrationResponse",
]
