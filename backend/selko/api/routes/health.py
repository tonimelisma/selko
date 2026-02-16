"""Health check endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import create_client

from selko.api.deps import get_config
from selko.api.schemas.common import ErrorCode, HealthDbResponse, HealthResponse, error_detail
from selko.config import Config

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
        # Create client for health check
        client = create_client(config.supabase_url, config.supabase_key)

        # Simple query to test connectivity
        # Using a table that exists but returns minimal data
        result = client.table("users").select("id").limit(1).execute()

        return HealthDbResponse(status="ok", database="connected")

    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail(ErrorCode.DATABASE_ERROR, "Database health check failed"),
        )
