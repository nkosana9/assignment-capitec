"""Shared FastAPI dependencies: app-scoped settings and storage, and API key auth."""

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from service.configuration.configuration import Settings
from service.storage import ObjectStore


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_store(request: Request) -> ObjectStore:
    return request.app.state.store


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    expected = settings.api_key.get_secret_value()
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid API key.")
