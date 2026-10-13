"""Interim pull request handler: process the diff and acknowledge the PR with a comment.

This is the placeholder for the full review pipeline (agents, aggregator, verifier).
"""

import logging

from reviewcrew.diff.filters import SkipReason
from reviewcrew.diff.processor import DiffOptions, ProcessedDiff, process_diff
from reviewcrew.github.client import GitHubClient
from reviewcrew.webhook.events import PullRequestEvent

logger = logging.getLogger(__name__)

MAX_SKIPPED_LISTED = 20

SKIP_REASON_LABELS: dict[SkipReason, str] = {
    "removed": "deleted",
    "binary": "binary",
    "submodule": "submodule",
    "symlink": "symlink",
    "no_changes": "no content changes",
    "lock_file": "lock file",
    "minified": "minified",
    "generated": "generated",
    "too_large": "too large",
}


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def acknowledgement_message(diff: ProcessedDiff) -> str:
    lines = [
        f"ReviewCrew received this PR ({_plural(diff.total_files, 'file')} changed).",
        "",
        f"- To review: {_plural(len(diff.files), 'file')} in {_plural(len(diff.chunks), 'chunk')}",
        f"- Skipped: {_plural(len(diff.skipped), 'file')}",
    ]
    for skipped in diff.skipped[:MAX_SKIPPED_LISTED]:
        # Paths come from the PR author; keep them from breaking out of the code span.
        path = skipped.path.replace("`", "'")
        lines.append(f"  - `{path}` ({SKIP_REASON_LABELS[skipped.reason]})")
    if len(diff.skipped) > MAX_SKIPPED_LISTED:
        lines.append(f"  - …and {len(diff.skipped) - MAX_SKIPPED_LISTED} more")
    return "\n".join(lines)


async def acknowledge_pull_request(
    event: PullRequestEvent, *, github: GitHubClient, options: DiffOptions
) -> None:
    installation_id = event.installation.id
    repo = event.repository.full_name
    number = event.pull_request.number

    diff_text = await github.get_pull_request_diff(installation_id, repo, number)
    diff = process_diff(diff_text, options)
    await github.create_issue_comment(installation_id, repo, number, acknowledgement_message(diff))
    logger.info(
        "Acknowledged %s#%s: %d files, %d to review in %d chunks, %d skipped",
        repo,
        number,
        diff.total_files,
        len(diff.files),
        len(diff.chunks),
        len(diff.skipped),
    )
