from reviewcrew.agents.security import SecurityAgent
from reviewcrew.diff.chunker import DiffChunk
from reviewcrew.diff.tokens import estimate_tokens
from reviewcrew.llm.base import TokenUsage
from reviewcrew.pipeline.budget import OUTPUT_ALLOWANCE_TOKENS, TokenBudget
from reviewcrew.pipeline.orchestrator import run_agents
from tests.fakes import RoutingLLM


def test_unlimited_budget_always_reserves() -> None:
    budget = TokenBudget(limit=None)

    assert budget.try_reserve(10**9)
    assert not budget.exhausted


def test_reservations_count_against_the_limit_until_settled() -> None:
    budget = TokenBudget(limit=1000)

    assert budget.try_reserve(600)
    assert not budget.try_reserve(600)  # 600 already reserved by an in-flight call
    budget.settle(600, TokenUsage(input_tokens=300, output_tokens=50))
    assert budget.spent == 350
    assert budget.try_reserve(600)  # 350 spent + 600 <= 1000


def test_exhausted_once_spent_reaches_the_limit() -> None:
    budget = TokenBudget(limit=100)
    budget.try_reserve(50)
    budget.settle(50, TokenUsage(input_tokens=120))

    assert budget.exhausted
    assert not budget.try_reserve(1)


async def test_orchestrator_skips_chunks_beyond_the_budget() -> None:
    chunks = [
        DiffChunk(index=i, paths=("a.py",), text="x" * 300, estimated_tokens=100) for i in range(3)
    ]
    agent = SecurityAgent(RoutingLLM({}))
    per_call = estimate_tokens(agent.system_prompt) + 100 + OUTPUT_ALLOWANCE_TOKENS
    # The first reservation fits; once its 120 real tokens are spent, the next one does not.
    budget = TokenBudget(limit=per_call + 119)

    (result,) = await run_agents(
        [agent],
        chunks,
        pr_title="t",
        agent_timeout_seconds=5,
        max_concurrent_calls=1,  # sequential, so the outcome is deterministic
        budget=budget,
    )

    assert result.skipped_chunks == 2
    assert result.usage.total_tokens == 120  # only one chunk was actually reviewed
