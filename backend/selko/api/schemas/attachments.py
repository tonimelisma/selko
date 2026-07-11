"""Attachment Pydantic schemas for API responses."""

from datetime import datetime

from pydantic import BaseModel, Field


class AttachmentResponse(BaseModel):
    """Attachment response model matching the attachments table schema."""

    id: str
    email_id: str
    user_id: str
    provider_attachment_id: str
    filename: str
    mime_type: str
    size_bytes: int
    storage_path: str | None = None
    content_hash: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
