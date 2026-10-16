import asyncio
from dataclasses import dataclass, field

import pytest

from reviewcrew.agents.base import BaseAgent
from reviewcrew.agents.models import AgentReport, FindingDraft
from reviewcrew.agents.performance import PerformanceAgent
from reviewcrew.agents.security import SecurityAgent
from reviewcrew.agents.tests import TestAgent
from reviewcrew.diff.chunker import DiffChunk
from reviewcrew.llm.base import SchemaT, StructuredResponse, TokenUsage
from reviewcrew.pipeline.orchestrator import run_agents
from tests.fakes import RoutingLLM

PATH = "app/users.py"
CHUNKS = [
    DiffChunk(index=i, paths=(PATH,), text=f"chunk-{i}", estimated_tokens=10) for i in range(2)
]


def report_for(system: str, user: str) -> AgentReport:
    """One finding per chunk, on a line derived from the chunk index."""
    index = int(user.split("chunk-")[1][0])
    return AgentReport(
        findings=[
            FindingDraft(
                category=RoutingLLM({}).agent_of(system),
                path=PATH,
                line=10 + index,
                end_line=None,
                severity="medium",
                confidence=0.9,
                title=f"Issue in chunk {index}",
                explanation="e",
                suggestion=None,
            )
        ]
    )


@dataclass
class ScriptedLLM:
    """Async fake: optional barrier/delay/crash per chunk, and a concurrency gauge."""

    barrier: asyncio.Barrier | None = None
    delay: dict[int, float] = field(default_factory=dict)  # chunk index -> seconds
    crash: bool = False
    gauge: list[int] = field(default_factory=lambda: [0, 0])  # [active, max seen]

    @property
    def name(self) -> str:
        return "scripted"

    async def complete_structured(
        self, *, system: str, user: str, schema: type[SchemaT]
    ) -> StructuredResponse[SchemaT]:
        self.gauge[0] += 1
        self.gauge[1] = max(self.gauge)
        try:
            if self.barrier is not None:
                await asyncio.wait_for(self.barrier.wait(), timeout=2)
            index = int(user.split("chunk-")[1][0])
            await asyncio.sleep(self.delay.get(index, 0))
            if self.crash:
                raise RuntimeError("simulated agent crash")
            value = report_for(system, user)
            assert isinstance(value, schema)
            return StructuredResponse(value=value, usage=TokenUsage(input_tokens=10), model="m")
        finally:
            self.gauge[0] -= 1


def three_agents(llms: list[ScriptedLLM]) -> list[BaseAgent]:
    return [SecurityAgent(llms[0]), PerformanceAgent(llms[1]), TestAgent(llms[2])]


async def test_the_three_agents_run_in_parallel() -> None:
    barrier = asyncio.Barrier(3)  # only releases once all three agents are calling at once
    llms = [ScriptedLLM(barrier=barrier) for _ in range(3)]

    results = await run_agents(
        three_agents(llms),
        CHUNKS[:1],
        pr_title="t",
        agent_timeout_seconds=5,
        max_concurrent_calls=3,
    )

    assert [r.agent for r in results] == ["security", "performance", "tests"]
    assert all(len(r.findings) == 1 and r.errors == () for r in results)


async def test_a_crashing_agent_does_not_affect_the_others() -> None:
    llms = [ScriptedLLM(), ScriptedLLM(crash=True), ScriptedLLM()]

    results = await run_agents(
        three_agents(llms), CHUNKS, pr_title="t", agent_timeout_seconds=5, max_concurrent_calls=4
    )

    security, performance, tests = results
    assert len(security.findings) == 2
    assert len(tests.findings) == 2
    assert performance.findings == ()
    assert performance.errors == (
        "chunk 0: crashed (RuntimeError)",
        "chunk 1: crashed (RuntimeError)",
    )


async def test_timeout_keeps_finished_chunks_and_reports_the_rest() -> None:
    slow = ScriptedLLM(delay={1: 30})  # chunk 1 never finishes in time

    (result,) = await run_agents(
        [SecurityAgent(slow)],
        CHUNKS,
        pr_title="t",
        agent_timeout_seconds=0.3,
        max_concurrent_calls=4,
    )

    assert [f.line for f in result.findings] == [10]  # chunk 0 survived
    assert result.errors == ("timed out after 0.3s; 1 of 2 chunks not reviewed",)
    assert 0.25 <= result.duration_seconds < 5  # coarse monotonic clock on Windows


async def test_concurrent_llm_calls_are_capped() -> None:
    gauge = [0, 0]
    llms = [ScriptedLLM(delay={0: 0.05, 1: 0.05}, gauge=gauge) for _ in range(3)]

    await run_agents(
        three_agents(llms), CHUNKS, pr_title="t", agent_timeout_seconds=5, max_concurrent_calls=2
    )

    assert gauge[1] == 2  # 6 calls in total, never more than 2 at once


async def test_no_chunks_gives_empty_results() -> None:
    results = await run_agents(
        three_agents([ScriptedLLM() for _ in range(3)]),
        [],
        pr_title="t",
        agent_timeout_seconds=1,
        max_concurrent_calls=1,
    )

    assert [(r.findings, r.errors) for r in results] == [((), ())] * 3


@pytest.mark.parametrize("agent_class", [SecurityAgent, PerformanceAgent, TestAgent])
def test_each_agent_has_its_own_checklist(agent_class: type[BaseAgent]) -> None:
    prompt = agent_class(ScriptedLLM()).system_prompt

    assert agent_class.role in prompt
    assert {"security": "Security", "performance": "Performance", "tests": "Test coverage"}[
        agent_class.name
    ] + " review checklist" in prompt
