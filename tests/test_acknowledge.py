import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from reviewcrew.github.auth import InstallationTokenProvider
from reviewcrew.github.client import GitHubClient
from reviewcrew.github.constants import DIFF_MEDIA_TYPE
from reviewcrew.pipeline.acknowledge import (
    acknowledge_pull_request,
    acknowledgement_message,
    count_changed_files,
)
from reviewcrew.webhook.events import PullRequestEvent
from tests.helpers import CLIENT_ID, pull_request_payload

API = "https://api.github.com"

DIFF = """\
diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1,2 +1,3 @@
 import os
+import sys
 print("hi")
diff --git a/README.md b/README.md
index 3333333..4444444 100644
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-# Old
+# New
"""


@pytest.fixture
async def github(private_key_pem: str) -> AsyncIterator[GitHubClient]:
    async with httpx.AsyncClient(base_url=API) as http:
        tokens = InstallationTokenProvider(http, client_id=CLIENT_ID, private_key=private_key_pem)
        yield GitHubClient(http, tokens)


def test_count_changed_files() -> None:
    assert count_changed_files(DIFF) == 2
    assert count_changed_files("") == 0


@pytest.mark.parametrize(
    ("count", "message"),
    [
        (0, "ReviewCrew received this PR (0 files changed)."),
        (1, "ReviewCrew received this PR (1 file changed)."),
        (5, "ReviewCrew received this PR (5 files changed)."),
    ],
)
def test_acknowledgement_message(count: int, message: str) -> None:
    assert acknowledgement_message(count) == message


@respx.mock
async def test_acknowledge_fetches_diff_and_comments(github: GitHubClient) -> None:
    expires = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    respx.post(f"{API}/app/installations/42/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "ghs_test", "expires_at": expires})
    )
    diff_route = respx.get(f"{API}/repos/octo/demo/pulls/7").mock(
        return_value=httpx.Response(200, text=DIFF)
    )
    comment_route = respx.post(f"{API}/repos/octo/demo/issues/7/comments").mock(
        return_value=httpx.Response(201, json={"id": 1})
    )
    event = PullRequestEvent.model_validate(pull_request_payload())

    await acknowledge_pull_request(event, github=github)

    diff_request = diff_route.calls.last.request
    assert diff_request.headers["Accept"] == DIFF_MEDIA_TYPE
    assert diff_request.headers["Authorization"] == "Bearer ghs_test"
    comment_request = comment_route.calls.last.request
    assert comment_request.headers["Authorization"] == "Bearer ghs_test"
    assert json.loads(comment_request.content) == {
        "body": "ReviewCrew received this PR (2 files changed)."
    }


@respx.mock
async def test_acknowledge_does_not_comment_when_diff_fails(github: GitHubClient) -> None:
    expires = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    respx.post(f"{API}/app/installations/42/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "ghs_test", "expires_at": expires})
    )
    respx.get(f"{API}/repos/octo/demo/pulls/7").mock(return_value=httpx.Response(404))
    comment_route = respx.post(f"{API}/repos/octo/demo/issues/7/comments")
    event = PullRequestEvent.model_validate(pull_request_payload())

    with pytest.raises(httpx.HTTPStatusError):
        await acknowledge_pull_request(event, github=github)

    assert not comment_route.called
