"""Retired Google Photos OAuth endpoint."""

from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/photos/auth")
async def photos_oauth_initiate() -> None:
    """Reject new Google Photos connections while the source is parked."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Google Photos ingestion is currently parked",
    )
