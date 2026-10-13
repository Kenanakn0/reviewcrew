"""Typed subset of the GitHub `pull_request` webhook payload and the filter for it."""

from pydantic import BaseModel

PROCESSED_ACTIONS = frozenset({"opened", "synchronize", "reopened", "ready_for_review"})


class Commit(BaseModel):
    sha: str


class PullRequest(BaseModel):
    number: int
    title: str
    draft: bool = False
    head: Commit


class Repository(BaseModel):
    full_name: str


class Installation(BaseModel):
    id: int


class PullRequestEvent(BaseModel):
    action: str
    number: int
    pull_request: PullRequest
    repository: Repository
    installation: Installation


def skip_reason(event: PullRequestEvent) -> str | None:
    """Return why `event` should not be reviewed, or `None` if it should be."""
    if event.action not in PROCESSED_ACTIONS:
        return f"action '{event.action}' is not reviewed"
    if event.pull_request.draft:
        return "pull request is a draft"
    return None
