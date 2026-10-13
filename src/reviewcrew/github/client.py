"""Thin async client for the GitHub REST endpoints ReviewCrew uses."""

from typing import Any
from urllib.parse import quote

import httpx

from reviewcrew.github.auth import InstallationTokenProvider
from reviewcrew.github.constants import (
    API_VERSION,
    DIFF_MEDIA_TYPE,
    JSON_MEDIA_TYPE,
    RAW_MEDIA_TYPE,
)


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

    async def get_file_content(
        self, installation_id: int, repo: str, path: str, ref: str, *, max_bytes: int
    ) -> str | None:
        """Return a file's text at `ref`, or None if it is missing, too large or not UTF-8."""
        response = await self._http.get(
            f"/repos/{repo}/contents/{quote(path, safe='/')}",
            params={"ref": ref},
            headers=await self._headers(installation_id, accept=RAW_MEDIA_TYPE),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        if len(response.content) > max_bytes:
            return None
        try:
            return response.content.decode("utf-8")
        except UnicodeDecodeError:
            return None

    async def create_review(
        self, installation_id: int, repo: str, number: int, payload: dict[str, Any]
    ) -> None:
        """Submit a pull request review (inline comments + body) in one request."""
        response = await self._http.post(
            f"/repos/{repo}/pulls/{number}/reviews",
            headers=await self._headers(installation_id),
            json=payload,
        )
        response.raise_for_status()
