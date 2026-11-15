"""Business logic dictating how statements are stored, how link lifetimes are chosen and capped and
who may see a statement.
"""

import io
import uuid
from datetime import datetime
from typing import BinaryIO
from zoneinfo import ZoneInfo

from service.configuration.configuration import Settings
from service.dtos.statement_dtos import Download, IssuedLink, StoredStatement
from service.errors import ObjectNotFound, StatementNotFound, StatementTooLarge, TtlExceedsMaximum
from service.libs.security import issue_download_token, verify_download_token
from service.libs.storage import ObjectStore, sanitize_filename

_DEFAULT_MIME_TYPE = "application/octet-stream"


def _size_of(data: BinaryIO) -> int:
    """Return the number of bytes in a seekable stream, leaving its position unchanged."""
    position = data.tell()
    data.seek(0, io.SEEK_END)
    size = data.tell()
    data.seek(position)
    return size


def upload_statement(
    store: ObjectStore,
    *,
    customer_id: str,
    raw_filename: str | None,
    raw_content_type: str | None,
    data: BinaryIO,
    max_bytes: int,
) -> StoredStatement:
    """Store a new statement under a freshly generated ID.

    Args:
        store: The object store to write to.
        customer_id: The customer who owns the statement.
        raw_filename: The client-supplied filename, sanitised before storage.
        raw_content_type: The client-supplied MIME type, defaulting to a generic binary type.
        data: The statement's contents.
        max_bytes: The largest statement that may be stored, in bytes.

    Returns:
        The new statement's ID and stored metadata.

    Raises:
        StatementTooLarge: If the statement is larger than `max_bytes`. Nothing is stored.
    """
    if _size_of(data) > max_bytes:
        raise StatementTooLarge(max_bytes)

    statement_id = uuid.uuid4().hex
    filename = sanitize_filename(raw_filename)
    content_type = raw_content_type or _DEFAULT_MIME_TYPE
    store.put(statement_id, data, content_type=content_type, filename=filename, owner=customer_id)
    return StoredStatement(
        statement_id=statement_id,
        filename=filename,
        content_type=content_type,
        customer_id=customer_id,
    )


def create_download_link(
    store: ObjectStore,
    settings: Settings,
    *,
    statement_id: str,
    customer_id: str,
    expiry_in_seconds: int | None,
    path_prefix: str,
) -> IssuedLink:
    """Create a signed download link for a statement the customer owns.

    Args:
        store: The object store used to check ownership.
        settings: The application settings, for TTL limits, signing and public URL.
        statement_id: The ID of the statement to link to.
        customer_id: The customer requesting the link; must own the statement.
        expiry_in_seconds: Requested lifetime in seconds, or None for the default.
        path_prefix: The route prefix the download endpoint is mounted under.

    Returns:
        The download URL and its expiry time in the configured display timezone.

    Raises:
        TtlExceedsMaximum: If the requested lifetime is longer than the configured maximum.
        StatementNotFound: If the statement does not exist or belongs to another customer.
    """
    ttl = expiry_in_seconds or settings.link_default_ttl_seconds
    if ttl > settings.link_max_ttl_seconds:
        raise TtlExceedsMaximum(settings.link_max_ttl_seconds)

    try:
        info = store.stat(statement_id)
    except ObjectNotFound as exception:
        raise StatementNotFound(statement_id) from exception

    # A statement that belongs to another customer gets the same outcome as a missing one,
    # so the API does not reveal which statement IDs exist.
    if info.owner != customer_id:
        raise StatementNotFound(statement_id)

    token, expires_at = issue_download_token(
        object_key=statement_id,
        filename=info.filename,
        owner=info.owner,
        signing_key=settings.link_signing_key.get_secret_value(),
        ttl_seconds=ttl,
    )
    return IssuedLink(
        url=f"{settings.public_base_url}{path_prefix}/downloads/{token}",
        expires_at=datetime.fromtimestamp(expires_at, tz=ZoneInfo(settings.display_timezone)),
    )


def get_download(store: ObjectStore, settings: Settings, *, token: str) -> Download:
    """Retrieve a downloadable statement using a signed token.

    Args:
        store: The object store containing the statement.
        settings: The application settings, for verifying the token.
        token: The signed download token.

    Returns:
        A Download object with the statement's filename and content stream.

    Raises:
        LinkExpired: If the token has expired.
        LinkInvalid: If the token is invalid.
        ObjectNotFound: If the statement does not exist.
    """
    claims = verify_download_token(token, settings.link_signing_key.get_secret_value())
    stream = store.open(claims["sub"])
    return Download(filename=claims["fn"], stream=stream)
