"""Hand reviews from the webhook to the worker through Redis, at most once per commit.

Two layers keep a `(repo, PR, head SHA)` from being reviewed twice:

1. The arq job ID is derived from that triple, so a redelivered webhook cannot enqueue a
   second job while the first one is queued or running.
2. The worker claims a long-lived Redis key before reviewing. A finished review keeps the
   claim (TTL), so later deliveries for the same commit are skipped; a failed or cancelled
   one releases it, so GitHub's redelivery (or arq's re-run) can try again.
"""

import logging
from typing import Literal

from arq import ArqRedis
from redis.asyncio import Redis

from reviewcrew.webhook.events import PullRequestEvent

logger = logging.getLogger(__name__)

REVIEW_JOB = "review_pull_request_job"
_JOB_ID_PREFIX = "review:"
_CLAIM_PREFIX = "reviewcrew:reviewed:"

DispatchOutcome = Literal["queued", "duplicate"]


def review_key(event: PullRequestEvent) -> str:
    pr = event.pull_request
    return f"{event.repository.full_name}#{pr.number}@{pr.head.sha}"


class ReviewClaims:
    """The per-commit 'already reviewed' marker."""

    def __init__(self, redis: Redis, *, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def is_claimed(self, key: str) -> bool:
        return bool(await self._redis.exists(_CLAIM_PREFIX + key))

    async def claim(self, key: str) -> bool:
        """Atomically take the claim; False if someone already holds or finished it."""
        return bool(await self._redis.set(_CLAIM_PREFIX + key, "running", nx=True, ex=self._ttl))

    async def complete(self, key: str) -> None:
        await self._redis.set(_CLAIM_PREFIX + key, "done", ex=self._ttl)

    async def release(self, key: str) -> None:
        await self._redis.delete(_CLAIM_PREFIX + key)


async def enqueue_review(
    pool: ArqRedis, claims: ReviewClaims, event: PullRequestEvent
) -> DispatchOutcome:
    key = review_key(event)
    if await claims.is_claimed(key):
        logger.info("Not queuing %s: already reviewed or in progress", key)
        return "duplicate"
    job = await pool.enqueue_job(
        REVIEW_JOB, event.model_dump(mode="json"), _job_id=_JOB_ID_PREFIX + key
    )
    if job is None:
        logger.info("Not queuing %s: a job for it is already queued", key)
        return "duplicate"
    logger.info("Queued review job for %s", key)
    return "queued"
