"""Request models for the HTTP API."""

from pydantic import BaseModel, Field

from service.api.schemas.responses import CUSTOMER_ID_PATTERN


class LinkRequest(BaseModel):
    """Request model for generating a download link."""

    customer_id: str = Field(pattern=CUSTOMER_ID_PATTERN)
    """The ID of the customer who owns the statement."""

    expires_in_seconds: int | None = Field(default=None, ge=60)
    """The number of seconds until the download link expires."""
