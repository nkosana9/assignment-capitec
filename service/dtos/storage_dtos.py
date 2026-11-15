"""Data transfer objects describing stored objects."""

from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class ObjectInfo:
    """Information about a stored object."""

    content_type: str
    """The MIME type of the object."""

    filename: str
    """The original filename of the object."""

    owner: str
    """The customer the object belongs to"""

    size: int
    """The size of the object in bytes."""


@dataclass
class ObjectStream:
    """A stream of an object's data along with its metadata."""

    chunks: Iterator[bytes]
    """An iterator yielding the object's data in chunks."""

    info: ObjectInfo
    """Metadata about the object."""
