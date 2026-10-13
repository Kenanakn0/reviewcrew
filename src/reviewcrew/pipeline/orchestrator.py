"""Run every agent over every chunk concurrently, isolating failures and enforcing timeouts."""

import asyncio
import logging
import time
from collections.abc import Sequence

from reviewcrew.agents.base import BaseAgent
from reviewcrew.agents.models import AgentResult
from reviewcrew.diff.chunker import DiffChunk

logger = logging.getLogger(__name__)


async def run_agents(
    agents: Sequence[BaseAgent],
    chunks: Sequence[DiffChunk],
    *,
    pr_title: str,
    agent_timeout_seconds: float,
    max_concurrent_calls: int,
) -> list[AgentResult]:
    """Return one result per agent, in the order of `agents`.

    Agents run in parallel; within an agent, chunks run in parallel too. A shared
    semaphore caps simultaneous LLM calls (rate limits). Each agent has its own deadline:
    chunks finished in time are kept, the rest are cancelled and reported as errors. Any
    exception is confined to the chunk that raised it, so one failing agent never stops
    the others or the review.
    """
    semaphore = asyncio.Semaphore(max_concurrent_calls)

    async def review(agent: BaseAgent, chunk: DiffChunk) -> AgentResult:
        async with semaphore:
            return await agent.review_chunk(chunk, pr_title=pr_title, chunk_count=len(chunks))

    async def run_agent(agent: BaseAgent) -> AgentResult:
        started = time.monotonic()
        tasks = [asyncio.create_task(review(agent, chunk)) for chunk in chunks]
        result = AgentResult(agent=agent.name)
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=agent_timeout_seconds)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
                logger.error(
                    "%s agent timed out after %gs (%d of %d chunks unfinished)",
                    agent.name,
                    agent_timeout_seconds,
                    len(pending),
                    len(tasks),
                )
                result += AgentResult(
                    agent=agent.name,
                    errors=(
                        f"timed out after {agent_timeout_seconds:g}s; "
                        f"{len(pending)} of {len(tasks)} chunks not reviewed",
                    ),
                )
            for task, chunk in zip(tasks, chunks, strict=True):
                if task not in done:
                    continue
                exc = task.exception()
                if exc is not None:
                    logger.error(
                        "%s agent crashed on chunk %d",
                        agent.name,
                        chunk.index,
                        exc_info=(type(exc), exc, exc.__traceback__),
                    )
                    result += AgentResult(
                        agent=agent.name,
                        errors=(f"chunk {chunk.index}: crashed ({type(exc).__name__})",),
                    )
                else:
                    result += task.result()
        return result.model_copy(update={"duration_seconds": time.monotonic() - started})

    return list(await asyncio.gather(*(run_agent(agent) for agent in agents)))
