"""End-to-end handling of one pull request:
diff -> agents (parallel) -> aggregate -> verify -> one GitHub review."""

import asyncio
import logging
import time
from collections.abc import Mapping, Sequence

import httpx

from reviewcrew.agents.base import BaseAgent
from reviewcrew.agents.models import AgentName
from reviewcrew.agents.registry import AGENT_CLASSES
from reviewcrew.diff.definitions import untested_definitions
from reviewcrew.diff.models import FileDiff
from reviewcrew.diff.processor import process_diff
from reviewcrew.github.client import GitHubClient
from reviewcrew.llm.base import LLMProvider
from reviewcrew.pipeline.aggregator import aggregate
from reviewcrew.pipeline.budget import TokenBudget
from reviewcrew.pipeline.options import ReviewOptions
from reviewcrew.pipeline.orchestrator import run_agents
from reviewcrew.pipeline.publisher import ReviewReport, build_review
from reviewcrew.pipeline.verifier import verify
from reviewcrew.redaction import secrets_in_diff
from reviewcrew.repo_config.loader import load_repo_config
from reviewcrew.rules.secrets import scan_secrets
from reviewcrew.webhook.events import PullRequestEvent

logger = logging.getLogger(__name__)

MAX_CONTEXT_FILE_BYTES = 1_000_000
CONTENT_FETCH_CONCURRENCY = 5


async def _fetch_head_contents(
    github: GitHubClient, event: PullRequestEvent, files: Sequence[FileDiff]
) -> dict[str, str]:
    """Head versions of `files` for surrounding context; failures just mean less context."""
    semaphore = asyncio.Semaphore(CONTENT_FETCH_CONCURRENCY)

    async def fetch(path: str) -> tuple[str, str | None]:
        async with semaphore:
            try:
                content = await github.get_file_content(
                    event.installation.id,
                    event.repository.full_name,
                    path,
                    event.pull_request.head.sha,
                    max_bytes=MAX_CONTEXT_FILE_BYTES,
                )
            except httpx.HTTPError as exc:
                logger.warning("Could not fetch head content for context: %s", exc)
                content = None
            return path, content

    pairs = await asyncio.gather(*(fetch(file.path) for file in files))
    return {path: content for path, content in pairs if content is not None}


async def review_pull_request(
    event: PullRequestEvent,
    *,
    github: GitHubClient,
    llm: LLMProvider,
    options: ReviewOptions,
    agent_classes: Mapping[AgentName, type[BaseAgent]] = AGENT_CLASSES,
) -> None:
    """`options` are the server defaults; the repository's `.reviewcrew.yml` refines them."""
    started = time.monotonic()
    installation_id = event.installation.id
    repo = event.repository.full_name
    number = event.pull_request.number
    head_sha = event.pull_request.head.sha

    repo_config = await load_repo_config(github, event)
    options = options.with_repo_config(repo_config.config)
    agents = [agent_classes[name](llm, language=options.language) for name in options.agents]

    diff_text = await github.get_pull_request_diff(installation_id, repo, number)
    diff = process_diff(diff_text, options.diff)
    if options.diff.context_lines > 0 and diff.files:
        contents = await _fetch_head_contents(github, event, list(diff.files.values()))
        diff = process_diff(diff_text, options.diff, new_contents=contents)

    files = list(diff.files.values())
    results = await run_agents(
        agents,
        diff.chunks,
        pr_title=event.pull_request.title,
        deleted_files=diff.deleted_paths,
        untested=untested_definitions(files),
        agent_timeout_seconds=options.agent_timeout_seconds,
        max_concurrent_calls=options.max_concurrent_llm_calls,
        budget=TokenBudget(options.token_budget),
    )
    # The secret scan belongs to the security review: off when the repository disables it.
    rule_findings = scan_secrets(files) if "security" in options.agents else None
    if rule_findings:
        logger.info("Secret scan: %s", "; ".join(f.log_label() for f in rule_findings))
    aggregation = aggregate(
        [*(f for r in results for f in r.findings), *(rule_findings or ())],
        options.aggregation,
    )
    report = ReviewReport(
        results=tuple(results),
        rule_findings=rule_findings,
        diff=diff,
        verified=verify(aggregation.findings, diff),
        below_confidence=aggregation.below_confidence,
        below_severity=aggregation.below_severity,
        duplicates_merged=aggregation.duplicates_merged,
        max_inline_comments=options.max_inline_comments,
        repo_config=repo_config,
        token_budget=options.token_budget,
        head_sha=head_sha,
        duration_seconds=time.monotonic() - started,
    )

    secrets = secrets_in_diff(diff.files.values())
    payload = build_review(report, secrets=secrets)
    try:
        await github.create_review(installation_id, repo, number, payload.to_api())
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 422 or not payload.comments:
            raise
        # GitHub rejected an inline anchor; keep the findings by moving all of them to the body.
        logger.warning(
            "Inline review rejected for %s#%s (422); retrying summary-only", repo, number
        )
        payload = build_review(report, secrets=secrets, allow_inline=False)
        await github.create_review(installation_id, repo, number, payload.to_api())

    logger.info(
        "Reviewed %s#%s: %d findings (%d inline, %d below confidence, %d merged), %d tokens, %.1fs",
        repo,
        number,
        len(aggregation.findings),
        len(payload.comments),
        aggregation.below_confidence,
        aggregation.duplicates_merged,
        sum(r.usage.total_tokens for r in results),
        time.monotonic() - started,
    )
