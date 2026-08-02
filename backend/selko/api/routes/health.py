"""Health check endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from selko.api.deps import get_config
from selko.api.schemas.common import ErrorCode, HealthDbResponse, HealthResponse, error_detail
from selko.config import Config
from selko.services.auth import get_service_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Basic health check endpoint.

    Returns 200 OK if the API is running.
    """
    return HealthResponse(status="ok")


@router.get("/health/db", response_model=HealthDbResponse)
async def health_db_check(
    config: Config = Depends(get_config),
) -> HealthDbResponse:
    """Database connectivity health check.

    Tests connection to Supabase and returns status.
    """
    try:
        # Must use the service role: 20260714000003 deliberately leaves `anon`
        # with no table privileges, so an anon probe reports the database as
        # down even when it is perfectly healthy. The key stays server-side and
        # only a status string is returned.
        client = get_service_client(config)

        # Simple query to test connectivity, returning minimal data.
        client.table("users").select("id").limit(1).execute()

        return HealthDbResponse(status="ok", database="connected")

    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail(ErrorCode.DATABASE_ERROR, "Database health check failed"),
        )
