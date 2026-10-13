"""Shared test constants and builders for GitHub webhook payloads."""

from typing import Any

WEBHOOK_SECRET = "test-webhook-secret"  # noqa: S105 - test fixture, not a real secret
CLIENT_ID = "Iv23liTestClientId"


def pull_request_payload(
    *,
    action: str = "opened",
    draft: bool = False,
    number: int = 7,
    repo: str = "octo/demo",
    installation_id: int = 42,
) -> dict[str, Any]:
    return {
        "action": action,
        "number": number,
        "pull_request": {
            "number": number,
            "title": "Add feature",
            "draft": draft,
            "head": {"sha": "abc123", "ref": "feature"},
            "base": {"sha": "def456", "ref": "main"},
        },
        "repository": {"full_name": repo, "name": repo.split("/")[1]},
        "installation": {"id": installation_id},
        "sender": {"login": "someone"},
    }
