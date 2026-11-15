"""Request and response models for the HTTP API."""

from datetime import datetime

from pydantic import BaseModel, Field

STATEMENT_ID_PATTERN = r"^[0-9a-f]{32}$"
# Customer IDs are stored as S3 metadata, so they are restricted to a safe ASCII set.
CUSTOMER_ID_PATTERN = r"^[A-Za-z0-9._:-]{1,128}$"


class StatementCreated(BaseModel):
    statement_id: str
    filename: str
    content_type: str
    customer_id: str


class LinkRequest(BaseModel):
    customer_id: str = Field(pattern=CUSTOMER_ID_PATTERN)
    expires_in_seconds: int | None = Field(default=None, ge=60)


class LinkCreated(BaseModel):
    url: str
    expires_at: datetime
