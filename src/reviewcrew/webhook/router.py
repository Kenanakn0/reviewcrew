"""`POST /webhook`: authenticate GitHub deliveries and dispatch pull request events."""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ValidationError

from reviewcrew.config import Settings
from reviewcrew.webhook.events import PullRequestEvent, skip_reason
from reviewcrew.webhook.signature import verify_signature

logger = logging.getLogger(__name__)

PullRequestHandler = Callable[[PullRequestEvent], Awaitable[None]]

router = APIRouter()


class WebhookResponse(BaseModel):
    status: Literal["accepted", "ignored", "pong"]
    detail: str | None = None


async def _run_handler(handler: PullRequestHandler, event: PullRequestEvent, delivery: str) -> None:
    """Run the handler after the response is sent; failures are logged, never raised."""
    try:
        await handler(event)
    except Exception:
        logger.exception(
            "Failed to process delivery %s for %s#%s",
            delivery,
            event.repository.full_name,
            event.pull_request.number,
        )


@router.post("/webhook", tags=["github"])
async def receive_webhook(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
    x_github_event: Annotated[str | None, Header()] = None,
    x_github_delivery: Annotated[str, Header()] = "unknown",
) -> WebhookResponse:
    settings: Settings = request.app.state.settings
    body = await request.body()

    secret = settings.github_webhook_secret.get_secret_value().encode()
    if not verify_signature(secret, body, x_hub_signature_256):
        logger.warning("Rejected delivery %s: invalid signature", x_github_delivery)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    if x_github_event == "ping":
        return WebhookResponse(status="pong")
    if x_github_event != "pull_request":
        return WebhookResponse(status="ignored", detail=f"event '{x_github_event}' is not handled")

    try:
        event = PullRequestEvent.model_validate_json(body)
    except ValidationError as exc:
        logger.warning("Rejected delivery %s: malformed pull_request payload", x_github_delivery)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Malformed payload") from exc

    reason = skip_reason(event)
    if reason is not None:
        logger.info(
            "Skipping %s#%s: %s", event.repository.full_name, event.pull_request.number, reason
        )
        return WebhookResponse(status="ignored", detail=reason)

    logger.info(
        "Accepted delivery %s: %s#%s (%s)",
        x_github_delivery,
        event.repository.full_name,
        event.pull_request.number,
        event.action,
    )
    handler: PullRequestHandler = request.app.state.pr_handler
    background_tasks.add_task(_run_handler, handler, event, x_github_delivery)
    response.status_code = status.HTTP_202_ACCEPTED
    return WebhookResponse(status="accepted")
