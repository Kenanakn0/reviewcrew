"""arq worker: runs queued reviews.

uv run reviewcrew-worker
"""

import logging
from contextlib import AsyncExitStack
from typing import Any, Literal

import httpx
from arq import func, run_worker
from arq.connections import RedisSettings

from reviewcrew.config import Settings, get_settings
from reviewcrew.github.auth import InstallationTokenProvider
from reviewcrew.github.client import GitHubClient
from reviewcrew.github.constants import USER_AGENT
from reviewcrew.jobs import REVIEW_JOB, ReviewClaims, review_key
from reviewcrew.llm.factory import open_llm_provider
from reviewcrew.logging_config import configure_logging
from reviewcrew.pipeline.review import review_pull_request
from reviewcrew.webhook.events import PullRequestEvent

logger = logging.getLogger(__name__)

Context = dict[str, Any]


async def startup(ctx: Context) -> None:
    """Open the long-lived GitHub and LLM clients once per worker process."""
    settings: Settings = ctx.get("settings") or get_settings()
    configure_logging(settings.log_level)
    stack = AsyncExitStack()
    http = await stack.enter_async_context(
        httpx.AsyncClient(
            base_url=str(settings.github_api_url),
            headers={"User-Agent": USER_AGENT},
            timeout=settings.github_timeout_seconds,
        )
    )
    tokens = InstallationTokenProvider(
        http,
        client_id=settings.github_app_client_id,
        private_key=settings.github_private_key_path.read_text(encoding="utf-8"),
    )
    ctx["stack"] = stack
    ctx["github"] = GitHubClient(http, tokens)
    ctx["llm"] = await stack.enter_async_context(open_llm_provider(settings))
    ctx["options"] = settings.review_options()
    ctx["claims"] = ReviewClaims(ctx["redis"], ttl_seconds=settings.review_dedup_ttl_seconds)


async def shutdown(ctx: Context) -> None:
    stack: AsyncExitStack | None = ctx.get("stack")
    if stack is not None:
        await stack.aclose()


async def review_pull_request_job(
    ctx: Context, payload: dict[str, Any]
) -> Literal["reviewed", "duplicate"]:
    event = PullRequestEvent.model_validate(payload)
    key = review_key(event)
    claims: ReviewClaims = ctx["claims"]
    if not await claims.claim(key):
        logger.info("Skipping %s: already reviewed or in progress", key)
        return "duplicate"
    try:
        await review_pull_request(
            event, github=ctx["github"], llm=ctx["llm"], options=ctx["options"]
        )
    except BaseException:
        # Includes cancellation on shutdown, after which arq re-runs the job.
        await claims.release(key)
        raise
    await claims.complete(key)
    return "reviewed"


class WorkerSettings:
    """Static part of the worker configuration; `run()` adds the environment-specific rest."""

    functions = (func(review_pull_request_job, name=REVIEW_JOB, max_tries=3),)
    on_startup = startup
    on_shutdown = shutdown
    keep_result = 0  # idempotency lives in ReviewClaims; a kept result would block redelivery


def run() -> None:
    """Entry point for `uv run reviewcrew-worker`."""
    settings = get_settings()
    run_worker(
        WorkerSettings,  # type: ignore[arg-type]  # arq's settings protocol is untyped here
        redis_settings=RedisSettings.from_dsn(str(settings.redis_url)),
        job_timeout=settings.review_job_timeout_seconds,
        max_jobs=settings.worker_max_jobs,
        ctx={"settings": settings},
    )
