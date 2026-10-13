import json
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx
import pytest

from reviewcrew.config import Settings
from reviewcrew.main import create_app
from reviewcrew.webhook.events import PullRequestEvent
from reviewcrew.webhook.signature import compute_signature
from tests.helpers import WEBHOOK_SECRET, pull_request_payload


class RecordingHandler:
    """Stands in for the queue: records events and returns a scripted outcome."""

    def __init__(
        self, *, fail: bool = False, outcome: Literal["queued", "duplicate"] = "queued"
    ) -> None:
        self.events: list[PullRequestEvent] = []
        self.fail = fail
        self.outcome: Literal["queued", "duplicate"] = outcome

    async def __call__(self, event: PullRequestEvent) -> Literal["queued", "duplicate"]:
        self.events.append(event)
        if self.fail:
            raise ConnectionError("redis down")
        return self.outcome


@pytest.fixture
def handler() -> RecordingHandler:
    return RecordingHandler()


@pytest.fixture
async def client(settings: Settings, handler: RecordingHandler) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, dispatch=handler)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _deliver(
    client: httpx.AsyncClient,
    payload: dict[str, Any] | bytes,
    *,
    event: str = "pull_request",
    signature: str | None = None,
) -> httpx.Response:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": "delivery-1",
        "X-Hub-Signature-256": signature or compute_signature(WEBHOOK_SECRET.encode(), body),
    }
    return await client.post("/webhook", content=body, headers=headers)


async def test_valid_pull_request_is_accepted_and_handled(
    client: httpx.AsyncClient, handler: RecordingHandler
) -> None:
    response = await _deliver(client, pull_request_payload(action="opened"))

    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "detail": None}
    assert [e.pull_request.number for e in handler.events] == [7]


async def test_invalid_signature_returns_401(
    client: httpx.AsyncClient, handler: RecordingHandler
) -> None:
    response = await _deliver(client, pull_request_payload(), signature="sha256=" + "0" * 64)

    assert response.status_code == 401
    assert handler.events == []


async def test_missing_signature_returns_401(client: httpx.AsyncClient) -> None:
    body = json.dumps(pull_request_payload()).encode()

    response = await client.post(
        "/webhook", content=body, headers={"X-GitHub-Event": "pull_request"}
    )

    assert response.status_code == 401


async def test_signature_is_checked_before_event_type(client: httpx.AsyncClient) -> None:
    response = await _deliver(client, {"zen": "hi"}, event="ping", signature="sha256=bad")

    assert response.status_code == 401


async def test_ping_returns_pong(client: httpx.AsyncClient) -> None:
    response = await _deliver(client, {"zen": "Keep it logically awesome."}, event="ping")

    assert response.status_code == 200
    assert response.json()["status"] == "pong"


async def test_other_events_are_ignored(
    client: httpx.AsyncClient, handler: RecordingHandler
) -> None:
    response = await _deliver(client, {"action": "created"}, event="issue_comment")

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert handler.events == []


async def test_draft_pull_request_is_ignored(
    client: httpx.AsyncClient, handler: RecordingHandler
) -> None:
    response = await _deliver(client, pull_request_payload(draft=True))

    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "detail": "pull request is a draft"}
    assert handler.events == []


async def test_unhandled_action_is_ignored(
    client: httpx.AsyncClient, handler: RecordingHandler
) -> None:
    response = await _deliver(client, pull_request_payload(action="closed"))

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert handler.events == []


async def test_malformed_payload_returns_400(client: httpx.AsyncClient) -> None:
    response = await _deliver(client, b'{"action": "opened"}')

    assert response.status_code == 400


async def test_queue_failure_returns_503_so_github_can_redeliver(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    failing = RecordingHandler(fail=True)
    transport = httpx.ASGITransport(app=create_app(settings, dispatch=failing))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await _deliver(client, pull_request_payload())

    assert response.status_code == 503
    assert response.json() == {"detail": "Review queue unavailable"}
    assert "Could not queue delivery delivery-1" in caplog.text


async def test_duplicate_delivery_is_acknowledged_without_queuing(settings: Settings) -> None:
    duplicate = RecordingHandler(outcome="duplicate")
    transport = httpx.ASGITransport(app=create_app(settings, dispatch=duplicate))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await _deliver(client, pull_request_payload())

    assert response.status_code == 200
    assert response.json()["status"] == "duplicate"
