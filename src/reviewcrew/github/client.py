"""Thin async client for the GitHub REST endpoints ReviewCrew uses."""

import httpx

from reviewcrew.github.auth import InstallationTokenProvider
from reviewcrew.github.constants import API_VERSION, DIFF_MEDIA_TYPE, JSON_MEDIA_TYPE


class GitHubClient:
    """Calls the GitHub API on behalf of an App installation.

    `repo` arguments are `owner/name` full names taken from verified webhook payloads.
    """

    def __init__(self, http: httpx.AsyncClient, tokens: InstallationTokenProvider) -> None:
        self._http = http
        self._tokens = tokens

    async def _headers(self, installation_id: int, accept: str = JSON_MEDIA_TYPE) -> dict[str, str]:
        token = await self._tokens.get_token(installation_id)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": accept,
            "X-GitHub-Api-Version": API_VERSION,
        }

    async def get_pull_request_diff(self, installation_id: int, repo: str, number: int) -> str:
        """Return the PR's unified diff as text."""
        response = await self._http.get(
            f"/repos/{repo}/pulls/{number}",
            headers=await self._headers(installation_id, accept=DIFF_MEDIA_TYPE),
        )
        response.raise_for_status()
        return response.text

    async def create_issue_comment(
        self, installation_id: int, repo: str, number: int, body: str
    ) -> None:
        """Post a top-level comment on a PR (PRs are issues in the REST API)."""
        response = await self._http.post(
            f"/repos/{repo}/issues/{number}/comments",
            headers=await self._headers(installation_id),
            json={"body": body},
        )
        response.raise_for_status()
