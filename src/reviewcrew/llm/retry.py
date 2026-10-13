"""Exponential backoff with full jitter for transient LLM failures."""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

from reviewcrew.llm.base import LLMTransientError

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]


async def with_retries[T](
    operation: Callable[[], Awaitable[T]],
    *,
    max_retries: int,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    sleep: Sleep = asyncio.sleep,
    description: str = "LLM request",
) -> T:
    """Run `operation`, retrying `LLMTransientError` up to `max_retries` times.

    The delay doubles each attempt (capped at `max_delay`) with full jitter; a server
    supplied `retry_after` is honoured when it is longer. Other errors propagate at once.
    """
    attempt = 0
    while True:
        try:
            return await operation()
        except LLMTransientError as exc:
            if attempt >= max_retries:
                raise
            delay = random.uniform(0, min(max_delay, base_delay * 2**attempt))  # noqa: S311
            if exc.retry_after is not None:
                delay = max(delay, min(exc.retry_after, max_delay))
            attempt += 1
            logger.warning(
                "%s failed (%s); retry %d/%d in %.1fs",
                description,
                exc,
                attempt,
                max_retries,
                delay,
            )
            await sleep(delay)
