"""Run every agent over every chunk concurrently, isolating failures and enforcing timeouts."""

import asyncio
import logging
import time
from collections.abc import Sequence

from reviewcrew.agents.base import BaseAgent
from reviewcrew.agents.models import AgentResult
from reviewcrew.diff.chunker import DiffChunk
from reviewcrew.diff.tokens import estimate_tokens
from reviewcrew.llm.base import TokenUsage
from reviewcrew.pipeline.budget import OUTPUT_ALLOWANCE_TOKENS, TokenBudget

logger = logging.getLogger(__name__)


async def run_agents(
    agents: Sequence[BaseAgent],
    chunks: Sequence[DiffChunk],
    *,
    pr_title: str,
    agent_timeout_seconds: float,
    max_concurrent_calls: int,
    budget: TokenBudget | None = None,
) -> list[AgentResult]:
    """Return one result per agent, in the order of `agents`.

    Agents run in parallel; within an agent, chunks run in parallel too. A shared
    semaphore caps simultaneous LLM calls (rate limits). Work is queued chunk by chunk,
    alternating between agents, so a limited token budget is shared fairly instead of the
    first agent taking all of it. Each agent has its own deadline: chunks finished in time
    are kept, the rest are cancelled and reported. Any exception is confined to the chunk
    that raised it, so one failing agent never stops the others or the review.
    """
    semaphore = asyncio.Semaphore(max_concurrent_calls)
    budget = budget or TokenBudget(limit=None)

    async def review(agent: BaseAgent, chunk: DiffChunk) -> AgentResult:
        async with semaphore:
            estimate = (
                estimate_tokens(agent.system_prompt)
                + chunk.estimated_tokens
                + OUTPUT_ALLOWANCE_TOKENS
            )
            if not await budget.reserve(estimate):
                logger.warning(
                    "%s agent: skipping chunk %d, token budget exhausted", agent.name, chunk.index
                )
                return AgentResult(agent=agent.name, skipped_chunks=1)
            usage = TokenUsage()
            try:
                result = await agent.review_chunk(chunk, pr_title=pr_title, chunk_count=len(chunks))
                usage = result.usage
                return result
            finally:
                await budget.settle(estimate, usage)

    # Chunk-major creation order: semaphore waiters are served first come, first served.
    tasks: dict[tuple[int, int], asyncio.Task[AgentResult]] = {}
    for chunk_index, chunk in enumerate(chunks):
        for agent_index, agent in enumerate(agents):
            tasks[agent_index, chunk_index] = asyncio.create_task(review(agent, chunk))
    started = time.monotonic()

    async def collect(agent_index: int, agent: BaseAgent) -> AgentResult:
        mine = [tasks[agent_index, chunk_index] for chunk_index in range(len(chunks))]
        result = AgentResult(agent=agent.name)
        if mine:
            done, pending = await asyncio.wait(mine, timeout=agent_timeout_seconds)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
                logger.error(
                    "%s agent timed out after %gs (%d of %d chunks unfinished)",
                    agent.name,
                    agent_timeout_seconds,
                    len(pending),
                    len(mine),
                )
                result += AgentResult(
                    agent=agent.name,
                    errors=(
                        f"timed out after {agent_timeout_seconds:g}s; "
                        f"{len(pending)} of {len(mine)} chunks not reviewed",
                    ),
                )
            for task, chunk in zip(mine, chunks, strict=True):
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

    return list(
        await asyncio.gather(*(collect(index, agent) for index, agent in enumerate(agents)))
    )
