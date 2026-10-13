"""End-to-end handling of one pull request: diff -> agents -> review."""

import asyncio
import logging
import time
from collections.abc import Sequence

import httpx

from reviewcrew.agents.base import BaseAgent
from reviewcrew.agents.models import AgentResult
from reviewcrew.diff.models import FileDiff
from reviewcrew.diff.processor import DiffOptions, process_diff
from reviewcrew.github.client import GitHubClient
from reviewcrew.pipeline.publisher import build_review
from reviewcrew.redaction import secrets_in_diff
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
    agents: Sequence[BaseAgent],
    options: DiffOptions,
) -> None:
    started = time.monotonic()
    installation_id = event.installation.id
    repo = event.repository.full_name
    number = event.pull_request.number
    head_sha = event.pull_request.head.sha

    diff_text = await github.get_pull_request_diff(installation_id, repo, number)
    diff = process_diff(diff_text, options)
    if options.context_lines > 0 and diff.files:
        contents = await _fetch_head_contents(github, event, list(diff.files.values()))
        diff = process_diff(diff_text, options, new_contents=contents)

    results: list[AgentResult] = []
    for agent in agents:
        result = AgentResult(agent=agent.name)
        for chunk in diff.chunks:
            result += await agent.review_chunk(
                chunk, pr_title=event.pull_request.title, chunk_count=len(diff.chunks)
            )
        results.append(result)

    secrets = secrets_in_diff(diff.files.values())
    duration = time.monotonic() - started
    payload = build_review(
        results, diff, head_sha=head_sha, secrets=secrets, duration_seconds=duration
    )
    try:
        await github.create_review(installation_id, repo, number, payload.to_api())
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 422 or not payload.comments:
            raise
        # GitHub rejected an inline anchor; keep the findings by moving all of them to the body.
        logger.warning(
            "Inline review rejected for %s#%s (422); retrying summary-only", repo, number
        )
        payload = build_review(
            results,
            diff,
            head_sha=head_sha,
            secrets=secrets,
            duration_seconds=duration,
            allow_inline=False,
        )
        await github.create_review(installation_id, repo, number, payload.to_api())

    logger.info(
        "Reviewed %s#%s: %d findings (%d inline), %d tokens, %.1fs",
        repo,
        number,
        sum(len(r.findings) for r in results),
        len(payload.comments),
        sum(r.usage.total_tokens for r in results),
        time.monotonic() - started,
    )
