"""Shared FastAPI dependencies: app-scoped settings and storage, and API key auth."""

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from service.configuration.configuration import Settings
from service.libs.storage import ObjectStore


def get_application_settings(request: Request) -> Settings:
    """Return the application settings attached to the running app.

    Args:
        request: The incoming request, used to reach the app state.

    Returns:
        The `Settings` instance stored on `app.state`.
    """
    return request.app.state.settings


def get_file_store(request: Request) -> ObjectStore:
    """Return the object store attached to the running app.

    Args:
        request: The incoming request, used to reach the app state.

    Returns:
        The `ObjectStore` instance stored on `app.state`.
    """
    return request.app.state.store


def require_api_key(
    settings: Annotated[Settings, Depends(get_application_settings)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Ensure that the request carries the configured API key.

    Args:
        settings: The application settings holding the expected key.
        x_api_key: The value of the `X-API-Key` header, if present.

    Raises:
        HTTPException: 401 if the header is missing or does not match the configured key.
    """
    expected = settings.api_key.get_secret_value()
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid API key.")
