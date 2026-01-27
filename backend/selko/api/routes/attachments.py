"""Attachment endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import StreamingResponse
from supabase import Client, PostgrestAPIError

from selko.api.deps import CurrentUser, get_authenticated_client, get_current_user
from selko.api.schemas.attachments import AttachmentResponse
from selko.config import load_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/attachments", tags=["attachments"])


@router.get("/{attachment_id}", response_model=AttachmentResponse)
async def get_attachment(
    attachment_id: Annotated[str, Path(description="Attachment UUID")],
    client: Client = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
) -> AttachmentResponse:
    """Get attachment metadata.

    Args:
        attachment_id: UUID of the attachment.

    Returns:
        Attachment metadata.

    Raises:
        404: Attachment not found or not owned by user.
        500: Failed to retrieve attachment.
    """
    try:
        result = (
            client.table("attachments")
            .select("*")
            .eq("id", attachment_id)
            .eq("user_id", user.id)
            .maybe_single()
            .execute()
        )

        if result is None or not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attachment not found",
            )

        return AttachmentResponse(**result.data)

    except HTTPException:
        raise
    except PostgrestAPIError as e:
        logger.error(f"Failed to get attachment: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve attachment",
        )


@router.get("/{attachment_id}/download")
async def download_attachment(
    attachment_id: Annotated[str, Path(description="Attachment UUID")],
    client: Client = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
) -> StreamingResponse:
    """Download attachment file.

    Args:
        attachment_id: UUID of the attachment.

    Returns:
        File stream with appropriate Content-Type header.

    Raises:
        404: Attachment not found or not owned by user.
        500: Failed to download file.
    """
    config = load_config()

    # Fetch attachment metadata
    try:
        result = (
            client.table("attachments")
            .select("*")
            .eq("id", attachment_id)
            .eq("user_id", user.id)
            .maybe_single()
            .execute()
        )

        if result is None or not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attachment not found",
            )

        attachment = result.data

    except HTTPException:
        raise
    except PostgrestAPIError as e:
        logger.error(f"Failed to get attachment: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve attachment metadata",
        )

    # Download file from Supabase Storage
    try:
        storage_path = attachment["storage_path"]
        if not storage_path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attachment file not found in storage",
            )

        # Get file from Supabase Storage
        file_data = client.storage.from_("attachments").download(storage_path)

        # Create streaming response
        return StreamingResponse(
            iter([file_data]),
            media_type=attachment["mime_type"],
            headers={
                "Content-Disposition": f'attachment; filename="{attachment["filename"]}"',
                "Content-Length": str(attachment["size_bytes"]),
            },
        )

    except Exception as e:
        logger.error(f"Failed to download attachment: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download file: {str(e)}",
        )
