"""Job status monitoring API endpoints."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from selko.api.deps import get_authenticated_client, get_current_user
from selko.api.schemas.common import PaginatedResponse
from selko.services.jobs import JobsError, get_job_status, get_pending_count

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/pending")
async def get_pending_jobs_count(
    client: Annotated[Client, Depends(get_authenticated_client)],
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Get count of pending jobs by type for the current user.

    Returns:
        Dict with job counts: {email_fetch: 0, email_process: 2, calendar_sync: 1}
    """
    try:
        counts = get_pending_count(client, user_id=user["id"])
        return {
            "user_id": user["id"],
            "pending_jobs": counts,
            "total": sum(counts.values()),
        }

    except JobsError as e:
        logger.error(f"Failed to get pending jobs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve pending jobs",
        )


@router.get("/{job_id}")
async def get_job(
    job_id: UUID,
    client: Annotated[Client, Depends(get_authenticated_client)],
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Get status of a specific job.

    Args:
        job_id: UUID of the job to query.

    Returns:
        Job details including status, attempts, errors.

    Raises:
        404: Job not found or not owned by user.
    """
    try:
        job = get_job_status(client, str(job_id))

        # Verify ownership
        if job["user_id"] != user["id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this job",
            )

        return job

    except JobsError as e:
        logger.error(f"Failed to get job: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )


@router.get("")
async def list_jobs(
    client: Annotated[Client, Depends(get_authenticated_client)],
    user: Annotated[dict, Depends(get_current_user)],
    status_filter: str = "all",
    limit: int = 20,
    offset: int = 0,
) -> PaginatedResponse:
    """List jobs for the current user.

    Args:
        status_filter: Filter by status (all, pending, processing, completed, failed, dead).
        limit: Maximum number of jobs to return.
        offset: Number of jobs to skip.

    Returns:
        Paginated list of jobs.
    """
    try:
        query = client.table("jobs").select(
            "*", count="exact"
        ).eq("user_id", user["id"]).order("created_at", desc=True)

        # Apply status filter
        if status_filter != "all":
            query = query.eq("status", status_filter)

        # Get total count
        count_result = query.execute()
        total = count_result.count or 0

        # Get paginated results
        result = query.range(offset, offset + limit - 1).execute()

        return PaginatedResponse(
            items=result.data,
            total=total,
            offset=offset,
            limit=limit,
        )

    except Exception as e:
        logger.error(f"Failed to list jobs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve jobs",
        )
