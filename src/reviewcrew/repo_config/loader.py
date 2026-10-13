"""Fetch `.reviewcrew.yml` for a pull request."""

import logging

import httpx

from reviewcrew.github.client import GitHubClient
from reviewcrew.repo_config.schema import CONFIG_PATH, MAX_CONFIG_BYTES, LoadedConfig, parse_config
from reviewcrew.webhook.events import PullRequestEvent

logger = logging.getLogger(__name__)


async def load_repo_config(github: GitHubClient, event: PullRequestEvent) -> LoadedConfig:
    """Read the config from the PR's *base* commit, not its head.

    Otherwise a pull request could edit `.reviewcrew.yml` to switch off the very
    reviewers (or paths) that would flag it.
    """
    try:
        text = await github.get_file_content(
            event.installation.id,
            event.repository.full_name,
            CONFIG_PATH,
            event.pull_request.base.sha,
            max_bytes=MAX_CONFIG_BYTES * 16,  # parse_config reports oversized files itself
        )
    except httpx.HTTPError as exc:
        logger.warning("Could not read %s, using defaults: %s", CONFIG_PATH, exc)
        return LoadedConfig(errors=("the file could not be read, so defaults were used",))
    loaded = parse_config(text)
    if loaded.errors:
        logger.info("Invalid %s in %s: %s", CONFIG_PATH, event.repository.full_name, loaded.errors)
    return loaded
