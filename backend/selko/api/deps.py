"""FastAPI dependencies for authentication and configuration."""

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from supabase import Client, create_client

from selko.api.schemas.common import ErrorCode, error_detail
from selko.config import Config, load_config
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


@lru_cache
def get_config() -> Config:
    """Load configuration (cached for performance)."""
    return load_config()


def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    config: Config = Depends(get_config),
) -> CurrentUser:
    """Validate JWT token and extract user information.

    Uses Supabase's auth.get_user() to validate the token, which works
    with both HS256 (cloud) and ES256 (local) JWT algorithms.

    Args:
        authorization: Bearer token from Authorization header.
        config: Application configuration.

    Returns:
        CurrentUser with id, email, and original token.

    Raises:
        HTTPException: 401 if token is missing, invalid, or expired.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail(ErrorCode.UNAUTHORIZED, "Missing Authorization header"),
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Extract token from "Bearer <token>"
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail(ErrorCode.UNAUTHORIZED, "Invalid Authorization header format. Use: Bearer <token>"),
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1]

    try:
        # Create client and validate token via Supabase auth
        client = create_client(config.supabase_url, config.supabase_key)

        # get_user() validates the token against Supabase auth
        user_response = client.auth.get_user(token)

        if not user_response or not user_response.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=error_detail(ErrorCode.UNAUTHORIZED, "Invalid or expired token"),
                headers={"WWW-Authenticate": "Bearer"},
            )

        user = user_response.user
        return CurrentUser(
            id=user.id,
            email=user.email,
            token=token,
        )

    except Exception as e:
        # Catch any auth errors (invalid token, expired, etc.)
        logger.warning(f"Token validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail(ErrorCode.UNAUTHORIZED, "Invalid or expired token"),
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_authenticated_client(
    user: CurrentUser = Depends(get_current_user),
    config: Config = Depends(get_config),
) -> Client:
    """Create Supabase client authenticated with user's JWT.

    This client will have RLS policies applied based on the user's identity.

    Args:
        user: Current authenticated user (from JWT).
        config: Application configuration.

    Returns:
        Supabase client with user's auth context.
    """
    # Create client with publishable key, then set the access token
    client = create_client(config.supabase_url, config.supabase_key)

    # Set the user's JWT so RLS policies apply
    client.auth.set_session(user.token, user.token)  # access_token, refresh_token

    return client


def get_service_role_client(config: Config = Depends(get_config)) -> Client:
    """Create Supabase client with service role key.

    Used for operations that need to bypass RLS, such as quota tracking.

    Args:
        config: Application configuration.

    Returns:
        Supabase client with service role privileges.

    Raises:
        HTTPException: 500 if service role key not configured.
    """
    if not config.supabase_service_role_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_detail(ErrorCode.SERVER_ERROR, "Server configuration error"),
        )
    return create_client(config.supabase_url, config.supabase_service_role_key)


def get_quota_service(
    service_client: Client = Depends(get_service_role_client),
) -> QuotaService:
    """Create QuotaService for rate limiting.

    Uses service role client to ensure atomic quota operations work
    regardless of RLS policies.

    Args:
        service_client: Supabase client with service role.

    Returns:
        Configured QuotaService instance.
    """
    return create_quota_service(service_client)


def get_llm_logging_service(
    service_client: Client = Depends(get_service_role_client),
) -> LLMLoggingService:
    """Create LLMLoggingService for LLM call auditing.

    Uses service role client to write logs regardless of RLS policies.

    Args:
        service_client: Supabase client with service role.

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
