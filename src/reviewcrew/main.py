"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from typing import Literal

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from reviewcrew import __version__
from reviewcrew.config import Settings, get_settings
from reviewcrew.github.auth import InstallationTokenProvider
from reviewcrew.github.client import GitHubClient
from reviewcrew.github.constants import USER_AGENT
from reviewcrew.pipeline.acknowledge import acknowledge_pull_request
from reviewcrew.webhook.router import PullRequestHandler
from reviewcrew.webhook.router import router as webhook_router


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


def _configure_logging(level: str) -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("reviewcrew").setLevel(level)


@asynccontextmanager
async def _github_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open one shared GitHub HTTP client for the app's lifetime and wire the PR handler."""
    settings: Settings = app.state.settings
    private_key = settings.github_private_key_path.read_text(encoding="utf-8")
    async with httpx.AsyncClient(
        base_url=str(settings.github_api_url),
        headers={"User-Agent": USER_AGENT},
        timeout=settings.github_timeout_seconds,
    ) as http:
        tokens = InstallationTokenProvider(
            http, client_id=settings.github_app_client_id, private_key=private_key
        )
        app.state.pr_handler = partial(acknowledge_pull_request, github=GitHubClient(http, tokens))
        yield


def create_app(
    settings: Settings | None = None, *, pr_handler: PullRequestHandler | None = None
) -> FastAPI:
    """Build the FastAPI application.

    Tests pass their own `Settings` and a fake `pr_handler`; in that case no GitHub
    client is created.
    """
    settings = settings or get_settings()
    _configure_logging(settings.log_level)

    app = FastAPI(
        title="ReviewCrew",
        version=__version__,
        lifespan=_github_lifespan if pr_handler is None else None,
    )
    app.state.settings = settings
    if pr_handler is not None:
        app.state.pr_handler = pr_handler

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
