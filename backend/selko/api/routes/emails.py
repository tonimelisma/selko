"""Email endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from supabase import Client, PostgrestAPIError

from selko.api.deps import CurrentUser, get_authenticated_client, get_current_user
from selko.api.schemas.common import PaginatedResponse
from selko.api.schemas.attachments import AttachmentResponse
from selko.api.schemas.emails import (
    BatchProcessRequest,
    EmailProcessResponse,
    EmailResponse,
    EmailSyncRequest,
    EmailSyncResponse,
)
from selko.config import load_config
from selko.services.emails import EmailError, fetch_emails_for_user
from selko.services.events import EventsError, process_email_for_events
from selko.services.gemini import get_gemini_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/emails", tags=["emails"])


@router.get("", response_model=PaginatedResponse[EmailResponse])
async def list_emails(
    client: Client = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[EmailResponse]:
    """List emails for the authenticated user.

    Emails are returned in reverse chronological order (newest first).
    Uses pagination with offset and limit.

    Args:
        offset: Number of records to skip (default 0).
        limit: Maximum records to return (default 20, max 100).

    Returns:
        Paginated list of emails.
    """
    try:
        # Get total count for pagination
        count_result = (
            client.table("emails")
            .select("id", count="exact")
            .eq("user_id", user.id)
            .execute()
        )
        total = count_result.count or 0

        # Get paginated results
        result = (
            client.table("emails")
            .select("*")
            .eq("user_id", user.id)
            .order("date_sent", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )

        emails = [EmailResponse(**row) for row in result.data]

        return PaginatedResponse(
            items=emails,
            total=total,
            offset=offset,
            limit=limit,
        )

    except PostgrestAPIError as e:
        logger.error(f"Failed to list emails: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve emails",
        )


@router.get("/{email_id}", response_model=EmailResponse)
async def get_email(
    email_id: Annotated[str, Path(description="Email UUID")],
    client: Client = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
) -> EmailResponse:
    """Get a single email by ID.

    Args:
        email_id: UUID of the email to retrieve.

    Returns:
        Email details.

    Raises:
        404: Email not found or not owned by user.
    """
    try:
        result = (
            client.table("emails")
            .select("*")
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

        return EmailResponse(**result.data)

    except HTTPException:
        raise
    except PostgrestAPIError as e:
        logger.error(f"Failed to get email: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve email",
        )


@router.post("/sync", response_model=EmailSyncResponse)
async def sync_emails(
    request: EmailSyncRequest,
    client: Client = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
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
        500: Email fetch or save failed.
    """
    config = load_config()

    try:
        result = fetch_emails_for_user(
            client=client,
            config=config,
            max_results=request.max_results,
            fetch_attachments=request.fetch_attachments,
        )

        return EmailSyncResponse(**result)

    except EmailError as e:
        logger.error(f"Failed to sync emails: {e}")
        if "No Gmail integration" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync emails: {str(e)}",
        )


@router.post("/{email_id}/process", response_model=EmailProcessResponse)
async def process_email(
    email_id: Annotated[str, Path(description="Email UUID")],
    client: Client = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
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
        500: Event extraction failed.
    """
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
            detail=f"Failed to extract events: {str(e)}",
        )


@router.post("/batch-process", response_model=EmailProcessResponse)
async def batch_process_emails(
    request: BatchProcessRequest,
    client: Client = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
) -> EmailProcessResponse:
    """Process multiple recent emails to extract events.

    Fetches the N most recent emails and processes each one with LLM
    to extract calendar events.

    Args:
        request: Batch process request with max_emails parameter.

    Returns:
        Aggregated processing results across all emails.

    Raises:
        500: Event extraction failed.
    """
    config = load_config()

    # Fetch recent emails
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
            detail=f"Batch processing failed: {str(e)}",
        )


@router.get("/{email_id}/attachments", response_model=list[AttachmentResponse])
async def list_email_attachments(
    email_id: Annotated[str, Path(description="Email UUID")],
    client: Client = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
) -> list[AttachmentResponse]:
    """List attachments for a specific email.

    Args:
        email_id: UUID of the email.

    Returns:
        List of attachments for the email.

    Raises:
        404: Email not found or not owned by user.
        500: Failed to retrieve attachments.
    """
    # Verify email exists and belongs to user
    try:
        email_result = (
            client.table("emails")
            .select("id")
            .eq("id", email_id)
            .eq("user_id", user.id)
            .maybe_single()
            .execute()
        )

        if email_result is None or not email_result.data:
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

    # Fetch attachments
    try:
        result = (
            client.table("attachments")
            .select("*")
            .eq("email_id", email_id)
            .eq("user_id", user.id)
            .order("filename")
            .execute()
        )

        return [AttachmentResponse(**row) for row in result.data]

    except PostgrestAPIError as e:
        logger.error(f"Failed to list attachments: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve attachments",
        )
