"""Request and response models for the HTTP API."""

from datetime import datetime

from pydantic import BaseModel

# Customer IDs are stored as S3 metadata, so they are restricted to a safe ASCII set.
CUSTOMER_ID_PATTERN = r"^[A-Za-z0-9._:-]{1,128}$"
# Statement IDs must be JSON-compatible 32-character strings.
STATEMENT_ID_PATTERN = r"^[0-9a-f]{32}$"


class StatementCreatedResponse(BaseModel):
    """Response model for a created statement."""

    content_type: str
    """The MIME type of the uploaded file."""

    customer_id: str
    """The ID of the customer who owns the statement."""

    filename: str
    """The name of the uploaded file."""

    statement_id: str
    """The ID of the created statement."""


class LinkCreatedResponse(BaseModel):
    """Response model for a created download link."""

    expires_at: datetime
    """The expiration time of the download link."""

    url: str
    """The URL of the download link."""
