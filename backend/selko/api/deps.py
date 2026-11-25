"""FastAPI dependencies for authentication and configuration."""

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from selko.api.schemas.common import ErrorCode, error_detail
from selko.config import Config, load_config
from selko.db.connection import Database
from selko.db.runtime import get_database
from selko.services import accounts
from selko.services.llm_gateway import LLMGateway, create_llm_gateway
from selko.services.llm_logging import (
    LLMLoggingService,
    get_llm_logging_service as create_llm_logging_service,
)
from selko.services.quotas import QuotaService, get_quota_service as create_quota_service

logger = logging.getLogger(__name__)


@dataclass
class CurrentUser:
    """Authenticated user information from JWT."""

    id: str
    email: str | None
    token: str
    session_id: str | None = None


@lru_cache
def get_config() -> Config:
    """Load configuration (cached for performance)."""
    return load_config()


def token_keys(config: Config) -> accounts.TokenKeys:
    if not config.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_detail(ErrorCode.SERVER_ERROR, "Server configuration error"),
        )
    return accounts.TokenKeys(config.jwt_secret, config.jwt_secret_previous)


def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    config: Config = Depends(get_config),
) -> CurrentUser:
    """The verified user behind the request's Selko access token.

    Verified locally (signature, expiry, issuer, audience): no database read
    and no network call per request (03-api-auth-web.md §B.6).
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail(ErrorCode.UNAUTHORIZED, "Missing Authorization header"),
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail(ErrorCode.UNAUTHORIZED, "Invalid Authorization header format. Use: Bearer <token>"),
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        identity = accounts.verify_access_token(token_keys(config), parts[1])
    except accounts.AuthError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail(ErrorCode.UNAUTHORIZED, "Invalid or expired token"),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return CurrentUser(id=identity.user_id, email=identity.email or None, token=identity.token,
                       session_id=identity.session_id)


def get_db() -> Database:
    """The process database. Every user-owned read takes the CurrentUser's id."""
    return get_database()


def get_authenticated_client(user: CurrentUser = Depends(get_current_user)) -> Database:
    """The database, for a route that has authenticated its user.

    Row-level security used to scope this client; now every data-layer
    function that touches user-owned rows takes ``user.id`` explicitly.
    """
    return get_database()


def get_service_role_client() -> Database:
    """The database, for service-wide work (quotas, logging)."""
    return get_database()


def get_quota_service(
    service_client: Database = Depends(get_service_role_client),
) -> QuotaService:
    """Create QuotaService for rate limiting.

    Args:
        service_client: The process database.

    Returns:
        Configured QuotaService instance.
    """
    return create_quota_service(service_client)


def get_llm_logging_service(
    service_client: Database = Depends(get_service_role_client),
) -> LLMLoggingService:
    """Create LLMLoggingService for LLM call auditing.

    Args:
        service_client: The process database.

    Returns:
        Configured LLMLoggingService instance.
    """
    return create_llm_logging_service(service_client)


def get_llm_gateway(
    config: Config = Depends(get_config),
    logging_service: LLMLoggingService = Depends(get_llm_logging_service),
    quota_service: QuotaService = Depends(get_quota_service),
) -> LLMGateway:
    """Create LLMGateway for unified LLM operations.

    The gateway handles rate limiting, logging, retries, and error handling
    for all LLM calls.

    Args:
        config: Application configuration.
        logging_service: Service for logging LLM calls.
        quota_service: Service for rate limiting.

    Returns:
        Configured LLMGateway instance.
    """
    return create_llm_gateway(config, logging_service, quota_service)
