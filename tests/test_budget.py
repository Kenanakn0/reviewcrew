import asyncio

from reviewcrew.agents.base import BaseAgent
from reviewcrew.agents.performance import PerformanceAgent
from reviewcrew.agents.security import SecurityAgent
from reviewcrew.agents.tests import TestAgent
from reviewcrew.diff.chunker import DiffChunk
from reviewcrew.diff.tokens import estimate_tokens
from reviewcrew.llm.base import TokenUsage
from reviewcrew.pipeline.budget import OUTPUT_ALLOWANCE_TOKENS, TokenBudget
from reviewcrew.pipeline.orchestrator import run_agents
from tests.fakes import RoutingLLM

CHUNKS = [
    DiffChunk(index=i, paths=("a.py",), text="x" * 300, estimated_tokens=100) for i in range(12)
]


def reservation(agent: BaseAgent) -> int:
    return estimate_tokens(agent.system_prompt) + 100 + OUTPUT_ALLOWANCE_TOKENS


async def test_unlimited_budget_always_reserves() -> None:
    budget = TokenBudget(limit=None)

    assert await budget.reserve(10**9)
    assert not budget.exhausted


async def test_reservations_count_against_the_limit_until_settled() -> None:
    budget = TokenBudget(limit=1000)
    assert await budget.reserve(600)

    # 600 is reserved by an in-flight call: the next reservation waits for it to settle.
    waiting = asyncio.create_task(budget.reserve(600))
    await asyncio.sleep(0)
    assert not waiting.done()

    await budget.settle(600, TokenUsage(input_tokens=300, output_tokens=50))
    assert await waiting  # 350 spent + 600 <= 1000
    assert budget.spent == 350


async def test_skips_only_when_nothing_is_in_flight() -> None:
    budget = TokenBudget(limit=100)
    assert await budget.reserve(50)
    await budget.settle(50, TokenUsage(input_tokens=120))

    assert budget.exhausted
    assert not await budget.reserve(1)


async def test_waiter_is_told_to_skip_when_the_last_call_settles_over_budget() -> None:
    budget = TokenBudget(limit=1000)
    assert await budget.reserve(900)
    waiting = asyncio.create_task(budget.reserve(500))
    await asyncio.sleep(0)

    await budget.settle(900, TokenUsage(input_tokens=700))  # 700 + 500 > 1000, nothing in flight

    assert await waiting is False


async def test_budget_is_used_up_instead_of_skipping_early() -> None:
    """Regression: chunks used to be skipped while reservations were still in flight,
    leaving most of the budget unspent."""
    agent = SecurityAgent(RoutingLLM({}))  # each call really costs 120 tokens
    budget = TokenBudget(limit=2 * reservation(agent))  # two reservations at a time

    (result,) = await run_agents(
        [agent],
        CHUNKS,
        pr_title="t",
        agent_timeout_seconds=5,
        max_concurrent_calls=4,
        budget=budget,
    )

    assert result.skipped_chunks == 0  # 12 x 120 tokens fit easily once calls settle
    assert result.usage.total_tokens == 12 * 120


async def test_orchestrator_skips_chunks_beyond_the_budget() -> None:
    agent = SecurityAgent(RoutingLLM({}))
    # The first reservation fits; once its 120 real tokens are spent, the next one does not.
    budget = TokenBudget(limit=reservation(agent) + 119)

    (result,) = await run_agents(
        [agent],
        CHUNKS[:3],
        pr_title="t",
        agent_timeout_seconds=5,
        max_concurrent_calls=1,
        budget=budget,
    )

    assert result.skipped_chunks == 2
    assert result.usage.total_tokens == 120


async def test_a_tight_budget_is_shared_fairly_between_agents() -> None:
    """Regression: the first agent used to take the whole budget."""
    llm = RoutingLLM({})
    agents = [SecurityAgent(llm), PerformanceAgent(llm), TestAgent(llm)]
    largest = max(reservation(agent) for agent in agents)
    # Room for 6 calls of 120 tokens plus one pessimistic reservation.
    budget = TokenBudget(limit=6 * 120 + largest)

    results = await run_agents(
        agents,
        CHUNKS,
        pr_title="t",
        agent_timeout_seconds=5,
        max_concurrent_calls=1,
        budget=budget,
    )

    reviewed = [len(CHUNKS) - r.skipped_chunks for r in results]
    assert sum(reviewed) == 7
    assert min(reviewed) >= 2, reviewed  # every agent got its turn
