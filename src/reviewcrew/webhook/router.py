"""`POST /webhook`: authenticate GitHub deliveries and queue pull request reviews."""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ValidationError

from reviewcrew.config import Settings
from reviewcrew.webhook.events import PullRequestEvent, skip_reason
from reviewcrew.webhook.signature import verify_signature

logger = logging.getLogger(__name__)

# Hands the event to the queue: "queued", or "duplicate" if this commit is already handled.
PullRequestDispatcher = Callable[[PullRequestEvent], Awaitable[Literal["queued", "duplicate"]]]

router = APIRouter()


class WebhookResponse(BaseModel):
    status: Literal["accepted", "duplicate", "ignored", "pong"]
    detail: str | None = None


@router.post("/webhook", tags=["github"])
async def receive_webhook(
    request: Request,
    response: Response,
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

    dispatch: PullRequestDispatcher = request.app.state.dispatch
    try:
        outcome = await dispatch(event)
    except Exception as exc:
        # Answer with an error so the delivery shows as failed and can be redelivered.
        logger.exception("Could not queue delivery %s", x_github_delivery)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="Review queue unavailable"
        ) from exc

    logger.info(
        "Delivery %s for %s#%s (%s): %s",
        x_github_delivery,
        event.repository.full_name,
        event.pull_request.number,
        event.action,
        outcome,
    )
    if outcome == "duplicate":
        return WebhookResponse(
            status="duplicate", detail="this commit is already reviewed or queued"
        )
    response.status_code = status.HTTP_202_ACCEPTED
    return WebhookResponse(status="accepted")
