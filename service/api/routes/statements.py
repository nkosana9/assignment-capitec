"""Contains all statement routes"""

import uuid
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Path, UploadFile, status
from fastapi.responses import StreamingResponse

from service.api.deps import get_settings_dep, get_store, require_api_key
from service.api.schemas import CUSTOMER_ID_PATTERN, STATEMENT_ID_PATTERN, LinkCreated, LinkRequest, StatementCreated
from service.configuration.configuration import Settings
from service.libs.security import LinkExpired, LinkInvalid, issue_download_token, verify_download_token
from service.storage import ObjectNotFound, ObjectStore, sanitize_filename

router = APIRouter(prefix="/api/v1/statements", tags=["statements"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=StatementCreated,
    dependencies=[Depends(require_api_key)],
)
def upload_file(
    statement: UploadFile,
    customer_id: Annotated[str, Form(pattern=CUSTOMER_ID_PATTERN)],
    store: Annotated[ObjectStore, Depends(get_store)],
) -> StatementCreated:
    statement_id = uuid.uuid4().hex
    filename = sanitize_filename(statement.filename)
    content_type = statement.content_type or "application/octet-stream"
    store.put(statement_id, statement.file, content_type=content_type, filename=filename, owner=customer_id)
    return StatementCreated(
        statement_id=statement_id,
        filename=filename,
        content_type=content_type,
        customer_id=customer_id,
    )


@router.post(
    "/{statement_id}/links",
    response_model=LinkCreated,
    dependencies=[Depends(require_api_key)],
)
def create_link(
    statement_id: Annotated[str, Path(pattern=STATEMENT_ID_PATTERN)],
    body: LinkRequest,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    store: Annotated[ObjectStore, Depends(get_store)],
) -> LinkCreated:
    ttl = body.expires_in_seconds or settings.link_default_ttl_seconds
    if ttl > settings.link_max_ttl_seconds:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"expires_in_seconds must be at most {settings.link_max_ttl_seconds}.",
        )
    try:
        info = store.stat(statement_id)
    except ObjectNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.") from exc

    # A file that belongs to another customer gets the same response as a missing one,
    # so the API does not reveal which file IDs exist.
    if info.owner != body.customer_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")

    token, expires_at = issue_download_token(
        object_key=statement_id,
        filename=info.filename,
        owner=info.owner,
        signing_key=settings.link_signing_key.get_secret_value(),
        ttl_seconds=ttl,
    )
    return LinkCreated(
        url=f"{settings.public_base_url}{router.prefix}/download/{token}",
        expires_at=datetime.fromtimestamp(expires_at, tz=ZoneInfo(settings.display_timezone)),
    )


@router.get("/download/{token}")
def download_file(
    token: str,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    store: Annotated[ObjectStore, Depends(get_store)],
) -> StreamingResponse:
    try:
        claims = verify_download_token(token, settings.link_signing_key.get_secret_value())
    except LinkExpired as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This download link has expired.") from exc
    except LinkInvalid as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid download link.") from exc

    try:
        obj = store.open(claims["sub"])
    except ObjectNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File no longer exists.") from exc

    return StreamingResponse(
        obj.chunks,
        media_type=obj.info.content_type,
        headers={
            "Content-Length": str(obj.info.size),
            "Content-Disposition": f'attachment; filename="{claims["fn"]}"',
            "Cache-Control": "private, no-store",
        },
    )
