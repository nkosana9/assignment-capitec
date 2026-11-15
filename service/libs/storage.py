"""Defines storage-agnostic object types and the `ObjectStore` interface."""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO, Protocol

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


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


class ObjectStore(Protocol):
    """Interface for an object storage backend."""

    def ensure_bucket(self) -> None:
        """Create the bucket if it does not exist."""
        ...

    def ping(self) -> None:
        """Raise if the storage server cannot be reached or the bucket is not accessible."""
        ...

    def put(self, key: str, data: BinaryIO, content_type: str, filename: str, owner: str) -> None:
        """Upload an object to the bucket."""
        ...

    def stat(self, key: str) -> ObjectInfo:
        """Retrieve metadata for an object."""
        ...

    def open(self, key: str) -> ObjectStream:
        """Open an object for reading."""
        ...


def sanitize_filename(name: str | None) -> str:
    """Reduce a client-supplied name to a safe ASCII basename."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE_CHARS.sub("_", base).strip("._")
    return cleaned[:200] or "download"
