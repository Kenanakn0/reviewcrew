"""Stage-1 pull request handler: fetch the diff and acknowledge the PR with a comment.

This is the placeholder for the full review pipeline (agents, aggregator, verifier).
"""

import logging

from reviewcrew.github.client import GitHubClient
from reviewcrew.webhook.events import PullRequestEvent

logger = logging.getLogger(__name__)


def count_changed_files(diff: str) -> int:
    """Count the files in a unified git diff by their `diff --git` headers."""
    return sum(1 for line in diff.splitlines() if line.startswith("diff --git "))


def acknowledgement_message(changed_files: int) -> str:
    noun = "file" if changed_files == 1 else "files"
    return f"ReviewCrew received this PR ({changed_files} {noun} changed)."


async def acknowledge_pull_request(event: PullRequestEvent, *, github: GitHubClient) -> None:
    installation_id = event.installation.id
    repo = event.repository.full_name
    number = event.pull_request.number

    diff = await github.get_pull_request_diff(installation_id, repo, number)
    changed_files = count_changed_files(diff)
    await github.create_issue_comment(
        installation_id, repo, number, acknowledgement_message(changed_files)
    )
    logger.info("Acknowledged %s#%s (%d files changed)", repo, number, changed_files)
