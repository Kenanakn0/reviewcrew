"""FastAPI application entry point."""

from typing import Literal

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from reviewcrew import __version__
from reviewcrew.config import Settings, get_settings


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application. Tests pass their own `Settings`."""
    app = FastAPI(title="ReviewCrew", version=__version__)
    app.state.settings = settings or get_settings()

    @app.get("/health", tags=["meta"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    return app


app = create_app()


def run() -> None:
    """Start the server with Uvicorn (`uv run reviewcrew`)."""
    settings = get_settings()
    uvicorn.run(
        "reviewcrew.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=settings.app_env == "development",
    )
