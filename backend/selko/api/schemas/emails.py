"""Email Pydantic schemas for API responses."""

from datetime import datetime

from pydantic import BaseModel


class EmailResponse(BaseModel):
    """Email response model matching the emails table schema."""

    id: str
    user_id: str
    gmail_id: str
    thread_id: str | None = None
    subject: str | None = None
    from_email: str | None = None
    from_name: str | None = None
    to_emails: list[str] | None = None
    date_sent: datetime | None = None
    snippet: str | None = None
    gmail_label_ids: list[str] | None = None
    has_attachments: bool = False

    # Auto-computed flags from trigger
    is_spam: bool = False
    is_trash: bool = False
    is_promotions: bool = False
    is_social: bool = False
    is_updates: bool = False
    is_forums: bool = False
    is_primary: bool = False
    is_important: bool = False
    is_starred: bool = False
    is_unread: bool = False

    created_at: datetime

    model_config = {"from_attributes": True}
