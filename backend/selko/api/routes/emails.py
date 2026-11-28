"""Email processing endpoints.

These endpoints require server-side secrets (Gmail API credentials, LLM API key).
Every read and write is scoped to the signed-in user.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status

from selko.api.deps import (
    CurrentUser,
    get_authenticated_client,
    get_config,
    get_current_user,
    get_llm_gateway,
    get_quota_service,
    get_service_role_client,
)
from selko.api.schemas.common import ErrorCode, error_detail
from selko.api.schemas.emails import (
    BatchProcessRequest,
    EmailProcessResponse,
    EmailReprocessResponse,
    EmailSyncRequest,
    EmailSyncResponse,
)
from selko.config import Config
from selko.db import emails as db_emails
from selko.db import events as db_events
from selko.db.connection import Database
from selko.db.errors import DbError, EmailActivelyLeased
from selko.services.emails import (
    EmailError,
    ExpiredCredentialsError,
    NoGmailIntegrationError,
    fetch_emails_for_user,
)
from selko.services.events import EventsError, process_email_for_events
from selko.services.llm_gateway import LLMGateway
from selko.services.quotas import QuotaExceededError, QuotaService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/emails", tags=["emails"])


@router.post("/{email_id}/reprocess", response_model=EmailReprocessResponse)
async def reprocess_email(
    email_id: Annotated[str, Path(description="Email UUID")],
    client: Database = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
) -> EmailReprocessResponse:
    """Atomically put one historical email back into the processing queue."""

    try:
        row = await client.run(db_emails.reprocess_email, client, user.id, email_id)
    except EmailActivelyLeased as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(
                ErrorCode.INVALID_REQUEST,
                "This email is already pending or being processed",
            ),
        ) from exc
    except DbError as exc:
        logger.error("Failed to reprocess email %s: %s", email_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_detail(ErrorCode.DATABASE_ERROR, "Failed to reprocess email"),
        ) from exc

    if not row:
        # The same response covers repeated clicks and a concurrent worker claim:
        # both leave the row pending/processing and therefore do not enqueue twice.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(
                ErrorCode.INVALID_REQUEST,
                "This email is already pending or being processed",
            ),
        )
    return EmailReprocessResponse(
        email_id=email_id,
        processing_status=row.get("processing_status", "pending"),
    )


@router.post("/sync", response_model=EmailSyncResponse)
async def sync_emails(
    request: EmailSyncRequest,
    response: Response,
    # Authentication resolves first: a request without a valid token is a
    # 401 before anything touches the database.
    user: CurrentUser = Depends(get_current_user),
    service_client: Database = Depends(get_service_role_client),
    config: Config = Depends(get_config),
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
            detail=error_detail(ErrorCode.QUOTA_EXCEEDED, "Daily email sync quota exceeded"),
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

    try:
        result = fetch_emails_for_user(
            client=service_client,
            config=config,
            max_results=request.max_results,
            fetch_attachments=request.fetch_attachments,
            user_id=user.id,
        )

        return EmailSyncResponse(
            fetched=result["fetched"],
            saved=result["saved"],
            attachments_downloaded=result["attachments_downloaded"],
        )

    except NoGmailIntegrationError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.CREDENTIALS_NOT_FOUND, "No Gmail integration found. Connect Gmail first."),
        )
    except ExpiredCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail(ErrorCode.CREDENTIALS_EXPIRED, "Gmail credentials expired or revoked. Please reconnect Gmail."),
        )
    except EmailError as e:
        logger.error(f"Failed to sync emails: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_detail(ErrorCode.SYNC_FAILED, "Failed to sync emails"),
        )


@router.post("/{email_id}/process", response_model=EmailProcessResponse)
async def process_email(
    email_id: Annotated[str, Path(description="Email UUID")],
    response: Response,
    client: Database = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
    gateway: LLMGateway = Depends(get_llm_gateway),
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
    # Verify email exists and belongs to user
    try:
        if not db_emails.exists_owned(client, user.id, email_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail(ErrorCode.EMAIL_NOT_FOUND, "Email not found"),
            )

    except HTTPException:
        raise
    except DbError as e:
        logger.error(f"Failed to fetch email: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_detail(ErrorCode.DATABASE_ERROR, "Failed to verify email"),
        )

    # Process email for events (gateway handles rate limiting)
    try:
        process_result = process_email_for_events(
            db=client,
            gateway=gateway,
            email_id=email_id,
            user_id=user.id,
        )

        # Get event IDs from database (events created/updated for this email)
        event_ids = db_events.event_ids_for_email(client, user.id, email_id)

        return EmailProcessResponse(
            num_events=process_result.get("num_events", 0),
            num_new=process_result.get("num_new", 0),
            num_updated=process_result.get("num_updated", 0),
            event_ids=event_ids,
        )

    except QuotaExceededError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_detail(ErrorCode.QUOTA_EXCEEDED, "Processing quota exceeded"),
            headers={
                "X-RateLimit-Limit": str(e.limit),
                "X-RateLimit-Remaining": "0",
            },
        )
    except EventsError as e:
        logger.error(f"Failed to process email for events: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_detail(ErrorCode.PROCESSING_FAILED, "Failed to extract events from email"),
        )


@router.post("/batch-process", response_model=EmailProcessResponse)
async def batch_process_emails(
    request: BatchProcessRequest,
    response: Response,
    client: Database = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
    gateway: LLMGateway = Depends(get_llm_gateway),
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
    # Fetch recent emails first
    try:
        email_ids = db_emails.list_ids_recent(client, user.id, request.max_emails)

        if not email_ids:
            logger.info("No emails found to process")
            return EmailProcessResponse(
                num_events=0,
                num_new=0,
                num_updated=0,
                event_ids=[],
            )

    except DbError as e:
        logger.error(f"Failed to fetch emails: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_detail(ErrorCode.DATABASE_ERROR, "Failed to fetch emails for processing"),
        )

    # Process each email (gateway handles per-call rate limiting)
    try:
        total_events = 0
        total_new = 0
        total_updated = 0
        all_event_ids: list[str] = []

        for email_id in email_ids:
            try:
                process_result = process_email_for_events(
                    db=client,
                    gateway=gateway,
                    email_id=email_id,
                    user_id=user.id,
                )

                total_events += process_result.get("num_events", 0)
                total_new += process_result.get("num_new", 0)
                total_updated += process_result.get("num_updated", 0)

                # Get event IDs for this email
                all_event_ids.extend(db_events.event_ids_for_email(client, user.id, email_id))

            except QuotaExceededError as e:
                # Stop batch processing when quota is exceeded
                logger.warning(f"Quota exceeded during batch processing: {e}")
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=error_detail(ErrorCode.QUOTA_EXCEEDED, "Quota exceeded after processing some emails"),
                    headers={
                        "X-RateLimit-Limit": str(e.limit),
                        "X-RateLimit-Remaining": "0",
                    },
                )
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

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Batch processing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_detail(ErrorCode.PROCESSING_FAILED, "Batch processing failed"),
        )
