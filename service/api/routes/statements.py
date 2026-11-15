"""Contains all statement routes"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Path, UploadFile, status
from fastapi.responses import StreamingResponse

from service.api.dependencies import get_application_settings, get_file_store, require_api_key
from service.api.schemas.requests import LinkRequest
from service.api.schemas.responses import (
    CUSTOMER_ID_PATTERN,
    STATEMENT_ID_PATTERN,
    LinkCreatedResponse,
    StatementCreatedResponse,
)
from service.configuration.configuration import Settings
from service.controllers import statement_controller
from service.errors import (
    LinkExpired,
    LinkInvalid,
    ObjectNotFound,
    StatementNotFound,
    TtlExceedsMaximum,
)
from service.libs.storage import ObjectStore

router = APIRouter(prefix="/api/v1/statements", tags=["statements"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=StatementCreatedResponse,
    dependencies=[Depends(require_api_key)],
)
def upload_file(
    statement: UploadFile,
    customer_id: Annotated[str, Form(pattern=CUSTOMER_ID_PATTERN)],
    store: Annotated[ObjectStore, Depends(get_file_store)],
) -> StatementCreatedResponse:
    """Store an uploaded statement for a customer.

    Args:
        statement: The uploaded file, as sent in the multipart `statement` field.
        customer_id: The customer the statement belongs to.
        store: The object store to write to.

    Returns:
        The ID and metadata of the stored statement.
    """
    stored = statement_controller.upload_statement(
        store,
        customer_id=customer_id,
        raw_filename=statement.filename,
        raw_content_type=statement.content_type,
        data=statement.file,
    )
    return StatementCreatedResponse(
        statement_id=stored.statement_id,
        filename=stored.filename,
        content_type=stored.content_type,
        customer_id=stored.customer_id,
    )


@router.post(
    "/{statement_id}/links",
    response_model=LinkCreatedResponse,
    dependencies=[Depends(require_api_key)],
)
def create_link(
    statement_id: Annotated[str, Path(pattern=STATEMENT_ID_PATTERN)],
    body: LinkRequest,
    settings: Annotated[Settings, Depends(get_application_settings)],
    store: Annotated[ObjectStore, Depends(get_file_store)],
) -> LinkCreatedResponse:
    """Issue a time-limited download link for a statement the customer owns.

    Args:
        statement_id: The ID of the statement to link to.
        body: The customer ID and optional lifetime for the link.
        settings: The application settings, for TTL limits and signing.
        store: The object store used to check ownership.

    Returns:
        The download URL and its expiry time.

    Raises:
        HTTPException: 400 if the requested lifetime exceeds the maximum; 404 if the statement
            does not exist or belongs to another customer.
    """
    try:
        link = statement_controller.create_download_link(
            store,
            settings,
            statement_id=statement_id,
            customer_id=body.customer_id,
            expiry_in_seconds=body.expires_in_seconds,
            path_prefix=router.prefix,
        )
    except TtlExceedsMaximum as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"expires_in_seconds must be at most {exc.max_seconds}.",
        ) from exc
    except StatementNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.") from exc
    return LinkCreatedResponse(url=link.url, expires_at=link.expires_at)


@router.get("/downloads/{token}")
def download_file(
    token: str,
    settings: Annotated[Settings, Depends(get_application_settings)],
    store: Annotated[ObjectStore, Depends(get_file_store)],
) -> StreamingResponse:
    """Stream a statement to the holder of a valid download link.

    Args:
        token: The signed download token from the link.
        settings: The application settings, for verifying the token.
        store: The object store to read from.

    Returns:
        A streaming attachment response with the statement's contents.

    Raises:
        HTTPException: 400 if the link has expired; 403 if the token is invalid; 404 if the
            statement no longer exists.
    """
    try:
        download = statement_controller.get_download(store, settings, token=token)
    except LinkExpired as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This download link has expired.") from exc
    except LinkInvalid as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid download link.") from exc
    except ObjectNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File no longer exists.") from exc

    file_object = download.stream
    return StreamingResponse(
        file_object.chunks,
        media_type=file_object.info.content_type,
        headers={
            "Content-Length": str(file_object.info.size),
            "Content-Disposition": f'attachment; filename="{download.filename}"',
            "Cache-Control": "private, no-store",
        },
    )
