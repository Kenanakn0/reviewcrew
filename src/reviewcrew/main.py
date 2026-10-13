"""FastAPI application entry point: receives webhooks and queues reviews."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from typing import Literal

import uvicorn
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from pydantic import BaseModel

from reviewcrew import __version__
from reviewcrew.config import Settings, get_settings
from reviewcrew.jobs import ReviewClaims, enqueue_review
from reviewcrew.logging_config import configure_logging
from reviewcrew.webhook.router import PullRequestDispatcher
from reviewcrew.webhook.router import router as webhook_router


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


@asynccontextmanager
async def _queue_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the Redis pool used to enqueue review jobs; the worker does the actual work."""
    settings: Settings = app.state.settings
    pool = await create_pool(RedisSettings.from_dsn(str(settings.redis_url)))
    try:
        claims = ReviewClaims(pool, ttl_seconds=settings.review_dedup_ttl_seconds)
        app.state.dispatch = partial(enqueue_review, pool, claims)
        yield
    finally:
        await pool.aclose()


def create_app(
    settings: Settings | None = None, *, dispatch: PullRequestDispatcher | None = None
) -> FastAPI:
    """Build the FastAPI application.

    Tests pass their own `Settings` and a fake `dispatch`; then no Redis pool is opened.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="ReviewCrew",
        version=__version__,
        lifespan=_queue_lifespan if dispatch is None else None,
    )
    app.state.settings = settings
    if dispatch is not None:
        app.state.dispatch = dispatch

    @app.get("/health", tags=["meta"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    app.include_router(webhook_router)
    return app


def run() -> None:
    """Start the server with Uvicorn (`uv run reviewcrew`)."""
    settings = get_settings()
    uvicorn.run(
        "reviewcrew.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=settings.app_env == "development",
    )
