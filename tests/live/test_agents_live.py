"""Runs the security agent against the configured real LLM. Costs money; skipped by default.

    uv run pytest -m live

Uses LLM_* / ANTHROPIC_API_KEY / OPENAI_COMPAT_* from the environment or `.env`.
"""

from pathlib import Path

import pytest
from pydantic import SecretStr

from reviewcrew.agents.registry import AGENT_CLASSES
from reviewcrew.agents.security import SecurityAgent
from reviewcrew.config import Settings
from reviewcrew.diff.processor import process_diff
from reviewcrew.llm.factory import open_llm_provider
from reviewcrew.pipeline.orchestrator import run_agents
from tests.helpers import load_diff

pytestmark = pytest.mark.live


async def test_security_agent_finds_sql_injection_and_hardcoded_key(tmp_path: Path) -> None:
    key_file = tmp_path / "unused.pem"
    key_file.write_text("unused", encoding="utf-8")
    settings = Settings(  # LLM settings from env/.env; GitHub ones are irrelevant here
        github_app_client_id="unused",
        github_private_key_path=key_file,
        github_webhook_secret=SecretStr("unused"),
    )
    diff = process_diff(load_diff("vulnerable.diff"))

    async with open_llm_provider(settings) as llm:
        result = await SecurityAgent(llm).review_chunk(
            diff.chunks[0], pr_title="Add user search and payments config", chunk_count=1
        )

    assert result.errors == ()
    located = {(f.path, f.line) for f in result.findings}
    assert located & {("app/users.py", 11), ("app/users.py", 12)}, result.findings
    assert ("app/settings.py", 9) in located, result.findings


async def test_all_agents_run_against_the_real_llm(tmp_path: Path) -> None:
    key_file = tmp_path / "unused.pem"
    key_file.write_text("unused", encoding="utf-8")
    settings = Settings(
        github_app_client_id="unused",
        github_private_key_path=key_file,
        github_webhook_secret=SecretStr("unused"),
    )
    diff = process_diff(load_diff("vulnerable.diff"))

    async with open_llm_provider(settings) as llm:
        results = await run_agents(
            [cls(llm) for cls in AGENT_CLASSES.values()],
            diff.chunks,
            pr_title="Add user search and payments config",
            agent_timeout_seconds=settings.review_agent_timeout_seconds,
            max_concurrent_calls=settings.llm_max_concurrency,
        )

    assert [r.agent for r in results] == ["security", "performance", "tests"]
    assert all(r.errors == () for r in results), [r.errors for r in results]
    assert all(r.usage.total_tokens > 0 for r in results)
