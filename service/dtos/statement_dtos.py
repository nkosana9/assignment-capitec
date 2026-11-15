"""Data transfer objects returned by the statement controller."""

from dataclasses import dataclass
from datetime import datetime

from service.dtos.storage_dtos import ObjectStream


@dataclass(frozen=True)
class StoredStatement:
    """Result of storing a statement."""

    content_type: str
    """The MIME type of the stored file."""

    customer_id: str
    """The ID of the customer who owns the statement."""

    filename: str
    """The name of the stored file."""

    statement_id: str
    """Uniquely identifies the stored statement."""


@dataclass(frozen=True)
class IssuedLink:
    """A download link and the time it stops working."""

    expires_at: datetime
    """The time at which the download link expires."""

    url: str
    """The URL that may be used to initiate a download."""


@dataclass(frozen=True)
class Download:
    """A verified download, ready to stream."""

    filename: str
    """The name of the file to be downloaded."""

    stream: ObjectStream
    """The content stream of the file."""
