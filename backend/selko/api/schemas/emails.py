"""Email Pydantic schemas for API responses."""

from datetime import datetime

from pydantic import BaseModel, Field


class EmailResponse(BaseModel):
    """Email response model matching the emails table schema."""

    id: str
    user_id: str
    provider_message_id: str
    email_provider: str
    thread_id: str | None = None
    subject: str | None = None
    from_email: str | None = None
    from_name: str | None = None
    to_emails: list[str] | None = None
    date_sent: datetime | None = None
    snippet: str | None = None
    provider_labels: list[str] | None = None
    has_attachments: bool = False

    # Auto-computed flags from trigger
    is_spam: bool = False
    is_trash: bool = False
    is_promotions: bool = False
    is_unread: bool = False

    created_at: datetime

    model_config = {"from_attributes": True}


class EmailSyncRequest(BaseModel):
    """Request model for manual email sync."""

    max_results: int = Field(default=10, ge=1, le=100, description="Maximum number of emails to fetch")
    fetch_attachments: bool = Field(default=True, description="Whether to download email attachments")


class EmailSyncResponse(BaseModel):
    """Response model for email sync operation."""

    fetched: int = Field(description="Number of emails fetched from the connected provider")
    saved: int = Field(description="Number of emails saved to database")
    attachments_downloaded: int = Field(description="Number of attachments downloaded")


class EmailProcessResponse(BaseModel):
    """Response model for processing email to extract events."""

    num_events: int = Field(description="Total number of events extracted")
    num_new: int = Field(description="Number of new events created")
    num_updated: int = Field(description="Number of existing events updated")
    event_ids: list[str] = Field(description="List of event UUIDs created/updated")


class EmailReprocessResponse(BaseModel):
    """Response returned when an historical email is queued again."""

    email_id: str
    processing_status: str
    queued: bool = True


class BatchProcessRequest(BaseModel):
    """Request model for batch processing emails."""

    max_emails: int = Field(default=10, ge=1, le=50, description="Maximum number of recent emails to process")
