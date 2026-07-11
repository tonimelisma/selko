"""Integration Pydantic schemas for API responses."""

from datetime import datetime

from pydantic import BaseModel


class IntegrationResponse(BaseModel):
    """Integration response model matching the integrations table schema."""

    id: str
    user_id: str
    provider: str
    status: str
    provider_email: str | None = None
    scopes: list[str] | None = None
    token_expiry: datetime | None = None
    sync_cursor: str | None = None
    last_sync_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    # Note: access_token and refresh_token are intentionally omitted
    # to avoid exposing sensitive credentials via API

    model_config = {"from_attributes": True}
