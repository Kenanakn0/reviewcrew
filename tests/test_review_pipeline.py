"""Stage 3 acceptance: a PR with a deliberate SQL injection and a hardcoded API key gets both
reported inline on the right lines. GitHub is mocked with respx; the LLM is a scripted fake
that answers like a model would, based on what is actually in the prompt."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from reviewcrew.agents.models import AgentReport, FindingDraft
from reviewcrew.agents.performance import PerformanceAgent
from reviewcrew.agents.security import SecurityAgent
from reviewcrew.agents.tests import TestAgent
from reviewcrew.diff.processor import DiffOptions
from reviewcrew.github.auth import InstallationTokenProvider
from reviewcrew.github.client import GitHubClient
from reviewcrew.llm.base import LLMRequestError
from reviewcrew.pipeline.options import ReviewOptions
from reviewcrew.pipeline.review import review_pull_request
from reviewcrew.webhook.events import PullRequestEvent
from tests.fakes import FakeLLM
from tests.helpers import CLIENT_ID, load_diff, pull_request_payload

API = "https://api.github.com"
REPO = "octo/demo"
KEY = "pk9f3Kq7Zr2LmX8vBn4TdW1yHs6Gc0Ea"
HEAD_SETTINGS = (
    '"""Application settings."""\n\nimport os\n\n'
    'DEBUG = os.environ.get("DEBUG") == "1"\n'
    'DATABASE_PATH = os.environ.get("DATABASE_PATH", "app.db")\n\n'
    f'# Payment provider\nPAYMENTS_API_KEY = "{KEY}"\nPAYMENT_TIMEOUT_SECONDS = 30\n'
)
HEAD_USERS = (
    '"""User lookups."""\n\nimport sqlite3\n\n\n'
    "def get_user_by_id(conn: sqlite3.Connection, user_id: int):\n"
    '    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()\n\n\n'
    "def find_users_by_name(conn: sqlite3.Connection, name: str):\n"
    "    query = f\"SELECT id, name, email FROM users WHERE name LIKE '%{name}%'\"\n"
    "    return conn.execute(query).fetchall()\n"
)


def security_model(system: str, user: str) -> AgentReport:
    """Stand-in for Claude: flags what a security reviewer would, at the line shown in the
    prompt's left column (so the test fails if the line numbering is wrong)."""
    findings = []
    for line in user.splitlines():
        number, _, code = line.partition(" + ")
        if not number.strip().isdigit():
            continue
        if 'f"SELECT' in code:
            findings.append(
                FindingDraft(
                    path="app/users.py",
                    line=int(number),
                    end_line=int(number) + 1,
                    severity="critical",
                    confidence=0.97,
                    title="SQL injection in find_users_by_name",
                    explanation="`name` is interpolated into the SQL string.",
                    suggestion='conn.execute("... WHERE name LIKE ?", (f"%{name}%",))',
                )
            )
        if 'API_KEY = "' in code:
            findings.append(
                FindingDraft(
                    path="app/settings.py",
                    line=int(number),
                    end_line=None,
                    severity="high",
                    confidence=0.95,
                    title="Hardcoded payments API key",
                    # A careless model quoting the secret; redaction must catch it.
                    explanation=f"The key {KEY} is committed to the repository.",
                    suggestion='PAYMENTS_API_KEY = os.environ["PAYMENTS_API_KEY"]',
                )
            )
    return AgentReport(findings=findings)


@pytest.fixture
async def github(private_key_pem: str) -> AsyncIterator[GitHubClient]:
    async with httpx.AsyncClient(base_url=API) as http:
        tokens = InstallationTokenProvider(http, client_id=CLIENT_ID, private_key=private_key_pem)
        yield GitHubClient(http, tokens)


@pytest.fixture
def event() -> PullRequestEvent:
    return PullRequestEvent.model_validate(pull_request_payload(repo=REPO))


def _mock_github(*, review_status: list[int] | None = None) -> respx.Route:
    expires = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    respx.post(f"{API}/app/installations/42/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "ghs_test", "expires_at": expires})
    )
    respx.get(f"{API}/repos/{REPO}/pulls/7").mock(
        return_value=httpx.Response(200, text=load_diff("vulnerable.diff"))
    )
    respx.get(f"{API}/repos/{REPO}/contents/app/settings.py").mock(
        return_value=httpx.Response(200, text=HEAD_SETTINGS)
    )
    respx.get(f"{API}/repos/{REPO}/contents/app/users.py").mock(
        return_value=httpx.Response(200, text=HEAD_USERS)
    )
    statuses = review_status or [200]
    return respx.post(f"{API}/repos/{REPO}/pulls/7/reviews").mock(
        side_effect=[
            httpx.Response(status, json={"message": "Unprocessable"} if status == 422 else {})
            for status in statuses
        ]
    )


def _payload(route: respx.Route, index: int = -1) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(route.calls[index].request.content)
    return result


@respx.mock
async def test_sql_injection_and_hardcoded_key_are_reported_on_the_right_lines(
    github: GitHubClient, event: PullRequestEvent
) -> None:
    reviews = _mock_github()
    llm = FakeLLM([security_model])

    await review_pull_request(
        event, github=github, agents=[SecurityAgent(llm)], options=ReviewOptions()
    )

    review = _payload(reviews)
    assert review["event"] == "COMMENT"
    assert review["commit_id"] == "abc123"
    anchors = {(c["path"], c.get("start_line"), c["line"]) for c in review["comments"]}
    assert anchors == {("app/users.py", 11, 12), ("app/settings.py", None, 9)}
    assert KEY not in json.dumps(review)  # masked even though the model repeated it
    assert "| 🔒 Security | 2 | critical |" in review["body"]


@respx.mock
async def test_head_contents_give_the_agent_extra_context(
    github: GitHubClient, event: PullRequestEvent
) -> None:
    _mock_github()
    llm = FakeLLM([AgentReport(findings=[])])

    await review_pull_request(
        event,
        github=github,
        agents=[SecurityAgent(llm)],
        options=ReviewOptions(diff=DiffOptions(context_lines=5)),
    )

    (_, user_prompt), *_ = llm.calls
    assert "     3   import sqlite3" in user_prompt  # outside the diff's own 3-line context


@respx.mock
async def test_rejected_inline_comments_fall_back_to_a_summary_only_review(
    github: GitHubClient, event: PullRequestEvent
) -> None:
    reviews = _mock_github(review_status=[422, 200])

    await review_pull_request(
        event,
        github=github,
        agents=[SecurityAgent(FakeLLM([security_model]))],
        options=ReviewOptions(),
    )

    assert reviews.call_count == 2
    retry = _payload(reviews)
    assert retry["comments"] == []
    assert "SQL injection in find_users_by_name" in retry["body"]
    assert KEY not in json.dumps(retry)


@respx.mock
async def test_review_is_still_posted_when_the_llm_fails(
    github: GitHubClient, event: PullRequestEvent
) -> None:
    reviews = _mock_github()

    await review_pull_request(
        event,
        github=github,
        agents=[SecurityAgent(FakeLLM([LLMRequestError("HTTP 401: invalid x-api-key")]))],
        options=ReviewOptions(),
    )

    review = _payload(reviews)
    assert review["comments"] == []
    assert "the LLM provider rejected the request" in review["body"]
    assert "invalid x-api-key" not in review["body"]  # provider details stay in the logs


def performance_model(system: str, user: str) -> AgentReport:
    return AgentReport(
        findings=[
            FindingDraft(
                path="app/users.py",
                line=12,
                end_line=None,
                severity="medium",
                confidence=0.8,
                title="Unbounded fetchall loads every matching row",
                explanation="A broad LIKE pattern can return the whole table.",
                suggestion="Paginate with LIMIT/OFFSET.",
            ),
            FindingDraft(  # same issue as the security agent's: must be merged
                path="app/users.py",
                line=11,
                end_line=None,
                severity="medium",
                confidence=0.6,
                title="SQL injection in find_users_by_name",
                explanation="Also a correctness problem.",
                suggestion=None,
            ),
            FindingDraft(  # below the default confidence threshold: must be hidden
                path="app/settings.py",
                line=10,
                end_line=None,
                severity="low",
                confidence=0.2,
                title="Timeout might be too long",
                explanation="Maybe.",
                suggestion=None,
            ),
        ]
    )


@respx.mock
async def test_three_agents_review_even_when_one_crashes(
    github: GitHubClient, event: PullRequestEvent
) -> None:
    """Stage 4 acceptance: agents run together, a crashed agent does not stop the review,
    duplicates are merged and low-confidence findings hidden."""
    reviews = _mock_github()

    await review_pull_request(
        event,
        github=github,
        agents=[
            SecurityAgent(FakeLLM([security_model])),
            PerformanceAgent(FakeLLM([performance_model])),
            TestAgent(FakeLLM([RuntimeError("simulated crash")])),
        ],
        options=ReviewOptions(),
    )

    review = _payload(reviews)
    anchors = {(c["path"], c.get("start_line"), c["line"]) for c in review["comments"]}
    assert anchors == {
        ("app/settings.py", None, 9),
        ("app/users.py", None, 12),
        ("app/users.py", 11, 12),
    }
    body = review["body"]
    assert "| 🔒 Security | 2 | critical |" in body
    assert "| ⚡ Performance | 1 | medium |" in body
    assert "| 🧪 Tests | 0 | — |" in body
    assert "⚠️ 1 error" in body
    assert "tests: chunk 0: crashed (RuntimeError)" in body
    assert "1 low-confidence finding hidden · 1 duplicate merged" in body
    assert KEY not in json.dumps(review)
