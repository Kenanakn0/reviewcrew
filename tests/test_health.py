from collections.abc import AsyncIterator
from typing import Literal

import httpx
import pytest

from reviewcrew import __version__
from reviewcrew.config import Settings
from reviewcrew.main import create_app
from reviewcrew.webhook.events import PullRequestEvent


async def _noop_dispatch(event: PullRequestEvent) -> Literal["queued", "duplicate"]:
    return "queued"


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, dispatch=_noop_dispatch)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_health_returns_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


async def test_unknown_route_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/does-not-exist")

    assert response.status_code == 404
