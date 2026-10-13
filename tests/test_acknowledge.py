import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from reviewcrew.diff.processor import DiffOptions, process_diff
from reviewcrew.github.auth import InstallationTokenProvider
from reviewcrew.github.client import GitHubClient
from reviewcrew.github.constants import DIFF_MEDIA_TYPE
from reviewcrew.pipeline.acknowledge import (
    MAX_SKIPPED_LISTED,
    acknowledge_pull_request,
    acknowledgement_message,
)
from reviewcrew.webhook.events import PullRequestEvent
from tests.helpers import CLIENT_ID, load_diff, pull_request_payload

API = "https://api.github.com"


@pytest.fixture
async def github(private_key_pem: str) -> AsyncIterator[GitHubClient]:
    async with httpx.AsyncClient(base_url=API) as http:
        tokens = InstallationTokenProvider(http, client_id=CLIENT_ID, private_key=private_key_pem)
        yield GitHubClient(http, tokens)


def _mock_token() -> None:
    expires = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    respx.post(f"{API}/app/installations/42/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "ghs_test", "expires_at": expires})
    )


def _new_file_diff(path: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
        f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1 @@\n+x\n"
    )


def test_message_for_mixed_fixture() -> None:
    message = acknowledgement_message(process_diff(load_diff("mixed.diff")))

    assert message.startswith("ReviewCrew received this PR (11 files changed).")
    assert "- To review: 4 files in 1 chunk" in message
    assert "- Skipped: 7 files" in message
    assert "  - `package-lock.json` (lock file)" in message
    assert "  - `src/removed.py` (deleted)" in message


def test_message_singular_and_no_skips() -> None:
    message = acknowledgement_message(process_diff(_new_file_diff("a.py")))

    assert message.splitlines() == [
        "ReviewCrew received this PR (1 file changed).",
        "",
        "- To review: 1 file in 1 chunk",
        "- Skipped: 0 files",
    ]


def test_message_escapes_backticks_in_paths() -> None:
    message = acknowledgement_message(process_diff(_new_file_diff("dist/a`b.js")))

    assert "`dist/a'b.js` (generated)" in message


def test_message_caps_the_skipped_list() -> None:
    diff_text = "".join(_new_file_diff(f"dist/f{i}.js") for i in range(MAX_SKIPPED_LISTED + 5))

    message = acknowledgement_message(process_diff(diff_text))

    assert message.count("(generated)") == MAX_SKIPPED_LISTED
    assert "…and 5 more" in message


@respx.mock
async def test_acknowledge_fetches_diff_and_comments(github: GitHubClient) -> None:
    _mock_token()
    diff_route = respx.get(f"{API}/repos/octo/demo/pulls/7").mock(
        return_value=httpx.Response(200, text=load_diff("mixed.diff"))
    )
    comment_route = respx.post(f"{API}/repos/octo/demo/issues/7/comments").mock(
        return_value=httpx.Response(201, json={"id": 1})
    )
    event = PullRequestEvent.model_validate(pull_request_payload())

    await acknowledge_pull_request(event, github=github, options=DiffOptions())

    diff_request = diff_route.calls.last.request
    assert diff_request.headers["Accept"] == DIFF_MEDIA_TYPE
    assert diff_request.headers["Authorization"] == "Bearer ghs_test"
    comment_request = comment_route.calls.last.request
    assert comment_request.headers["Authorization"] == "Bearer ghs_test"
    body = json.loads(comment_request.content)["body"]
    assert body.startswith("ReviewCrew received this PR (11 files changed).")


@respx.mock
async def test_acknowledge_does_not_comment_when_diff_fails(github: GitHubClient) -> None:
    _mock_token()
    respx.get(f"{API}/repos/octo/demo/pulls/7").mock(return_value=httpx.Response(404))
    comment_route = respx.post(f"{API}/repos/octo/demo/issues/7/comments")
    event = PullRequestEvent.model_validate(pull_request_payload())

    with pytest.raises(httpx.HTTPStatusError):
        await acknowledge_pull_request(event, github=github, options=DiffOptions())

    assert not comment_route.called
