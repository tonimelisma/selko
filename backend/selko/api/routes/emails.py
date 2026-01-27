"""Email processing endpoints.

These endpoints require server-side secrets (Gmail API credentials, LLM API key).
For direct email queries, use Supabase client from frontend.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from supabase import Client, PostgrestAPIError

from selko.api.deps import (
    CurrentUser,
    get_authenticated_client,
    get_current_user,
    get_quota_service,
)
from selko.api.schemas.emails import (
    BatchProcessRequest,
    EmailProcessResponse,
    EmailSyncRequest,
    EmailSyncResponse,
)
from selko.config import load_config
from selko.services.emails import EmailError, fetch_emails_for_user
from selko.services.events import EventsError, process_email_for_events
from selko.services.gemini import get_gemini_client
from selko.services.quotas import QuotaService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/emails", tags=["emails"])


@router.post("/sync", response_model=EmailSyncResponse)
async def sync_emails(
    request: EmailSyncRequest,
    response: Response,
    client: Client = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
    quota_service: QuotaService = Depends(get_quota_service),
) -> EmailSyncResponse:
    """Manually trigger email fetch from Gmail.

    Fetches emails from Gmail and stores them in the database.
    Optionally downloads and stores email attachments.

    Args:
        request: Sync request with max_results and fetch_attachments options.

    Returns:
        Sync result with counts of fetched, saved, and downloaded items.

    Raises:
        404: No Gmail integration found.
        429: Email sync quota exceeded.
        500: Email fetch or save failed.
    """
    # Check email sync quota
    quota_result = quota_service.check_and_increment(user.id, "email_syncs")
    if not quota_result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily email sync quota exceeded",
            headers={
                "X-RateLimit-Limit": str(quota_result.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": quota_result.resets_at,
            },
        )

    # Add quota headers to response
    response.headers["X-RateLimit-Limit"] = str(quota_result.limit)
    response.headers["X-RateLimit-Remaining"] = str(quota_result.remaining)
    response.headers["X-RateLimit-Reset"] = quota_result.resets_at

    config = load_config()

    try:
        result = fetch_emails_for_user(
            client=client,
            config=config,
            max_results=request.max_results,
            fetch_attachments=request.fetch_attachments,
        )

        return EmailSyncResponse(
            fetched=result["fetched"],
            saved=result["saved"],
            attachments_downloaded=result["attachments_downloaded"],
        )

    except EmailError as e:
        logger.error(f"Failed to sync emails: {e}")
        if "No Gmail integration" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No Gmail integration found. Connect Gmail first.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync emails",
        )


@router.post("/{email_id}/process", response_model=EmailProcessResponse)
async def process_email(
    email_id: Annotated[str, Path(description="Email UUID")],
    response: Response,
    client: Client = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
    quota_service: QuotaService = Depends(get_quota_service),
) -> EmailProcessResponse:
    """Process an email to extract calendar events.

    Uses LLM to analyze email content and attachments, extracting structured
    calendar events. Creates new events or updates existing ones based on
    semantic matching.

    Args:
        email_id: UUID of the email to process.

    Returns:
        Processing result with event counts and IDs.

    Raises:
        404: Email not found or not owned by user.
        429: LLM quota exceeded.
        500: Event extraction failed.
    """
    # Check LLM quota BEFORE any expensive operations
    quota_result = quota_service.check_and_increment(user.id, "llm_calls")
    if not quota_result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily LLM processing quota exceeded",
            headers={
                "X-RateLimit-Limit": str(quota_result.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": quota_result.resets_at,
            },
        )

    # Add quota headers to response
    response.headers["X-RateLimit-Limit"] = str(quota_result.limit)
    response.headers["X-RateLimit-Remaining"] = str(quota_result.remaining)
    response.headers["X-RateLimit-Reset"] = quota_result.resets_at

    config = load_config()

    # Verify email exists and belongs to user
    try:
        result = (
            client.table("emails")
            .select("id")
            .eq("id", email_id)
            .eq("user_id", user.id)
            .maybe_single()
            .execute()
        )

        if result is None or not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Email not found",
            )

    except HTTPException:
        raise
    except PostgrestAPIError as e:
        logger.error(f"Failed to fetch email: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify email",
        )

    # Process email for events
    try:
        gemini_client = get_gemini_client(config)
        process_result = process_email_for_events(
            supabase_client=client,
            gemini_client=gemini_client,
            email_id=email_id,
            user_id=user.id,
        )

        # Get event IDs from database (events created/updated for this email)
        events_result = (
            client.table("event_sources")
            .select("event_id")
            .eq("email_id", email_id)
            .eq("is_undone", False)
            .execute()
        )

        event_ids = [row["event_id"] for row in events_result.data]

        return EmailProcessResponse(
            num_events=process_result.get("num_events", 0),
            num_new=process_result.get("num_new", 0),
            num_updated=process_result.get("num_updated", 0),
            event_ids=event_ids,
        )

    except EventsError as e:
        logger.error(f"Failed to process email for events: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to extract events from email",
        )


@router.post("/batch-process", response_model=EmailProcessResponse)
async def batch_process_emails(
    request: BatchProcessRequest,
    response: Response,
    client: Client = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
    quota_service: QuotaService = Depends(get_quota_service),
) -> EmailProcessResponse:
    """Process multiple recent emails to extract events.

    Fetches the N most recent emails and processes each one with LLM
    to extract calendar events.

    Args:
        request: Batch process request with max_emails parameter.

    Returns:
        Aggregated processing results across all emails.

    Raises:
        429: LLM quota exceeded.
        500: Event extraction failed.
    """
    config = load_config()

    # Fetch recent emails first to know how many LLM calls we need
    try:
        result = (
            client.table("emails")
            .select("id")
            .eq("user_id", user.id)
            .order("date_sent", desc=True)
            .limit(request.max_emails)
            .execute()
        )

        email_ids = [row["id"] for row in result.data]

        if not email_ids:
            logger.info("No emails found to process")
            return EmailProcessResponse(
                num_events=0,
                num_new=0,
                num_updated=0,
                event_ids=[],
            )

    except PostgrestAPIError as e:
        logger.error(f"Failed to fetch emails: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch emails for processing",
        )

    # Check LLM quota for all emails BEFORE processing
    # Each email requires 1 LLM call
    num_emails = len(email_ids)
    quota_result = quota_service.check_and_increment(user.id, "llm_calls", num_emails)
    if not quota_result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily LLM quota exceeded. Requested {num_emails} calls, only {quota_result.remaining + num_emails} remaining.",
            headers={
                "X-RateLimit-Limit": str(quota_result.limit),
                "X-RateLimit-Remaining": str(quota_result.remaining),
                "X-RateLimit-Reset": quota_result.resets_at,
            },
        )

    # Add quota headers to response
    response.headers["X-RateLimit-Limit"] = str(quota_result.limit)
    response.headers["X-RateLimit-Remaining"] = str(quota_result.remaining)
    response.headers["X-RateLimit-Reset"] = quota_result.resets_at

    # Process each email
    try:
        gemini_client = get_gemini_client(config)

        total_events = 0
        total_new = 0
        total_updated = 0
        all_event_ids = []

        for email_id in email_ids:
            try:
                process_result = process_email_for_events(
                    supabase_client=client,
                    gemini_client=gemini_client,
                    email_id=email_id,
                    user_id=user.id,
                )

                total_events += process_result.get("num_events", 0)
                total_new += process_result.get("num_new", 0)
                total_updated += process_result.get("num_updated", 0)

                # Get event IDs for this email
                events_result = (
                    client.table("event_sources")
                    .select("event_id")
                    .eq("email_id", email_id)
                    .eq("is_undone", False)
                    .execute()
                )

                event_ids = [row["event_id"] for row in events_result.data]
                all_event_ids.extend(event_ids)

            except EventsError as e:
                logger.error(f"Failed to process email {email_id}: {e}")
                continue

        logger.info(
            f"Batch processed {len(email_ids)} emails: "
            f"{total_new} new, {total_updated} updated events"
        )

        return EmailProcessResponse(
            num_events=total_events,
            num_new=total_new,
            num_updated=total_updated,
            event_ids=list(set(all_event_ids)),  # Deduplicate
        )

    except Exception as e:
        logger.error(f"Batch processing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Batch processing failed",
        )
