"""Application factory: wires settings, storage and routes into a FastAPI app."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool

from service.api.routes import health, statements
from service.configuration.configuration import Settings, get_settings
from service.integrations.s3 import S3Store
from service.libs.storage import ObjectStore

# The `version` file lives at the project root, one level above the `service` package.
VERSION = (Path(__file__).resolve().parents[1] / "version").read_text().strip()


def create_app(settings: Settings | None = None, store: ObjectStore | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = store or S3Store.from_settings(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
        await run_in_threadpool(store.ensure_bucket)
        yield

    app = FastAPI(
        title="Account Statement Service",
        lifespan=lifespan,
        version=VERSION,
    )
    # Routes read these through the dependencies in service/api/deps.py.
    app.state.settings = settings
    app.state.store = store
    app.include_router(health.router)
    app.include_router(statements.router)
    return app
