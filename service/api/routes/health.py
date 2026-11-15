"""Application health endpoints for the orchestrator"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from service.api.deps import get_store
from service.libs.storage import ObjectStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ops"])


@router.get("/livez")
def livez() -> dict[str, str]:
    """Used to check that the application is able to respond."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz(store: Annotated[ObjectStore, Depends(get_store)]) -> JSONResponse:
    """Responds with readiness status if the service can do real work."""
    try:
        store.ping()
    except Exception:
        # Any failure means "not ready". The detail goes to the log, not the response.
        logger.exception("readiness check: storage is unreachable")
        return JSONResponse(
            {"status": "unavailable", "checks": {"storage": "unreachable"}},
            status_code=503,
        )
    return JSONResponse({"status": "ready", "checks": {"storage": "ok"}})
