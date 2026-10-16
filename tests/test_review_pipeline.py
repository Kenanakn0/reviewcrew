"""Review pipeline against mocked GitHub (respx) and a scripted LLM that answers like a model
would, based on what is actually in the prompt."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from reviewcrew.agents.models import AgentReport, FindingDraft
from reviewcrew.diff.processor import DiffOptions
from reviewcrew.github.auth import InstallationTokenProvider
from reviewcrew.github.client import GitHubClient
from reviewcrew.llm.base import LLMRequestError
from reviewcrew.pipeline.options import ReviewOptions
from reviewcrew.pipeline.review import review_pull_request
from reviewcrew.webhook.events import PullRequestEvent
from tests.fakes import RoutingLLM
from tests.helpers import CLIENT_ID, load_diff, pull_request_payload

API = "https://api.github.com"
REPO = "octo/demo"
BASE_SHA = "def456"  # pull_request_payload's base commit
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
SECURITY_ONLY = ReviewOptions(agents=("security",))


def _draft(path: str, line: int, **fields: Any) -> FindingDraft:
    defaults: dict[str, Any] = {
        "category": "security",
        "end_line": None,
        "severity": "high",
        "confidence": 0.9,
        "title": "Issue",
        "explanation": "e",
        "suggestion": None,
    }
    return FindingDraft.model_validate({"path": path, "line": line, **defaults, **fields})


def security_model(system: str, user: str) -> AgentReport:
    """Flags what a security reviewer would, at the line shown in the prompt's left column
    (so the test fails if line numbering is wrong)."""
    findings = []
    for line in user.splitlines():
        number, _, code = line.partition(" + ")
        if not number.strip().isdigit():
            continue
        if 'f"SELECT' in code:
            findings.append(
                _draft(
                    "app/users.py",
                    int(number),
                    end_line=int(number) + 1,
                    severity="critical",
                    confidence=0.97,
                    title="SQL injection in find_users_by_name",
                    explanation="`name` is interpolated into the SQL string.",
                )
            )
        if 'API_KEY = "' in code:
            findings.append(
                _draft(
                    "app/settings.py",
                    int(number),
                    title="Hardcoded payments API key",
                    # A careless model quoting the secret; redaction must catch it.
                    explanation=f"The key {KEY} is committed to the repository.",
                )
            )
    return AgentReport(findings=findings)


def performance_model(system: str, user: str) -> AgentReport:
    return AgentReport(
        findings=[
            _draft(
                "app/users.py",
                12,
                category="performance",
                severity="medium",
                confidence=0.8,
                title="Unbounded fetchall loads every matching row",
            ),
            # Same issue as the security agent's, mislabelled by the model: must be merged.
            _draft(
                "app/users.py",
                11,
                category="performance",
                severity="medium",
                confidence=0.6,
                title="SQL injection",
            ),
            # Below the default confidence threshold: must be hidden.
            _draft(
                "app/settings.py",
                10,
                category="performance",
                severity="low",
                confidence=0.2,
                title="Long timeout",
            ),
            # Honestly labelled as another agent's area: must be dropped before aggregation.
            _draft("app/settings.py", 9, category="security", title="Hardcoded API key"),
        ]
    )


@pytest.fixture
async def github(private_key_pem: str) -> AsyncIterator[GitHubClient]:
    async with httpx.AsyncClient(base_url=API) as http:
        tokens = InstallationTokenProvider(http, client_id=CLIENT_ID, private_key=private_key_pem)
        yield GitHubClient(http, tokens)


@pytest.fixture
def event() -> PullRequestEvent:
    return PullRequestEvent.model_validate(pull_request_payload(repo=REPO))


def mock_github(
    *, review_status: list[int] | None = None, repo_config: str | None = None
) -> tuple[respx.Route, respx.Route]:
    expires = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    respx.post(f"{API}/app/installations/42/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "ghs_test", "expires_at": expires})
    )
    respx.get(f"{API}/repos/{REPO}/pulls/7").mock(
        return_value=httpx.Response(200, text=load_diff("vulnerable.diff"))
    )
    config_route = respx.get(f"{API}/repos/{REPO}/contents/.reviewcrew.yml").mock(
        return_value=httpx.Response(404)
        if repo_config is None
        else httpx.Response(200, text=repo_config)
    )
    respx.get(f"{API}/repos/{REPO}/contents/app/settings.py").mock(
        return_value=httpx.Response(200, text=HEAD_SETTINGS)
    )
    respx.get(f"{API}/repos/{REPO}/contents/app/users.py").mock(
        return_value=httpx.Response(200, text=HEAD_USERS)
    )
    reviews = respx.post(f"{API}/repos/{REPO}/pulls/7/reviews").mock(
        side_effect=[
            httpx.Response(status, json={"message": "Unprocessable"} if status == 422 else {})
            for status in review_status or [200]
        ]
    )
    return reviews, config_route


def payload_of(route: respx.Route, index: int = -1) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(route.calls[index].request.content)
    return result


def anchors(review: dict[str, Any]) -> set[tuple[str, int | None, int]]:
    return {(c["path"], c.get("start_line"), c["line"]) for c in review["comments"]}


@respx.mock
async def test_sql_injection_and_hardcoded_key_are_reported_on_the_right_lines(
    github: GitHubClient, event: PullRequestEvent
) -> None:
    reviews, _ = mock_github()
    llm = RoutingLLM({"security": security_model})

    await review_pull_request(event, github=github, llm=llm, options=SECURITY_ONLY)

    review = payload_of(reviews)
    assert review["event"] == "COMMENT"
    assert review["commit_id"] == "abc123"
    assert anchors(review) == {("app/users.py", 11, 12), ("app/settings.py", None, 9)}
    assert KEY not in json.dumps(review)  # masked even though the model repeated it
    assert "| 🔒 Security | 2 | critical |" in review["body"]


@respx.mock
async def test_head_contents_give_the_agent_extra_context(
    github: GitHubClient, event: PullRequestEvent
) -> None:
    mock_github()
    llm = RoutingLLM({})
    options = SECURITY_ONLY.model_copy(update={"diff": DiffOptions(context_lines=5)})

    await review_pull_request(event, github=github, llm=llm, options=options)

    (_, user_prompt), *_ = llm.calls
    assert "     3   import sqlite3" in user_prompt  # outside the diff's own 3-line context


@respx.mock
async def test_rejected_inline_comments_fall_back_to_a_summary_only_review(
    github: GitHubClient, event: PullRequestEvent
) -> None:
    reviews, _ = mock_github(review_status=[422, 200])

    await review_pull_request(
        event, github=github, llm=RoutingLLM({"security": security_model}), options=SECURITY_ONLY
    )

    assert reviews.call_count == 2
    retry = payload_of(reviews)
    assert retry["comments"] == []
    assert "SQL injection in find_users_by_name" in retry["body"]
    assert KEY not in json.dumps(retry)


@respx.mock
async def test_review_is_still_posted_when_the_llm_fails(
    github: GitHubClient, event: PullRequestEvent
) -> None:
    reviews, _ = mock_github()
    llm = RoutingLLM({"security": LLMRequestError("HTTP 401: invalid x-api-key")})

    await review_pull_request(event, github=github, llm=llm, options=SECURITY_ONLY)

    review = payload_of(reviews)
    # The deterministic secret scan does not depend on the LLM.
    assert [(c["path"], c["line"]) for c in review["comments"]] == [("app/settings.py", 9)]
    assert "Secret scan (rule)" in review["comments"][0]["body"]
    assert KEY not in json.dumps(review)
    assert "the LLM provider rejected the request" in review["body"]
    assert "invalid x-api-key" not in review["body"]  # provider details stay in the logs


@respx.mock
async def test_three_agents_review_even_when_one_crashes(
    github: GitHubClient, event: PullRequestEvent
) -> None:
    """Agents run together, a crashed agent does not stop the review, duplicates are merged
    and low-confidence findings hidden."""
    reviews, _ = mock_github()
    llm = RoutingLLM(
        {
            "security": security_model,
            "performance": performance_model,
            "tests": RuntimeError("simulated crash"),
        }
    )

    await review_pull_request(event, github=github, llm=llm, options=ReviewOptions())

    review = payload_of(reviews)
    assert anchors(review) == {
        ("app/settings.py", None, 9),
        ("app/users.py", None, 12),
        ("app/users.py", 11, 12),
    }
    body = review["body"]
    assert "| 🔒 Security | 2 | critical |" in body
    assert "| ⚡ Performance | 1 (3 raw) | medium |" in body
    assert "| 🧪 Tests | 0 | — |" in body
    # The scan found the key too; the security agent's finding on that line absorbed it.
    assert "| 🔑 Secret scan (rule) | 0 (1 raw) | — | — | — | ✅ |" in body
    assert "tests: chunk 0: crashed (RuntimeError)" in body
    assert (
        "1 low-confidence finding hidden · "
        "1 finding outside the reporting agent's area dropped · 2 duplicates merged"
    ) in body
    assert KEY not in json.dumps(review)


# --- .reviewcrew.yml -----------------------------------------------------------------------


@respx.mock
async def test_repo_config_is_read_from_the_base_commit(
    github: GitHubClient, event: PullRequestEvent
) -> None:
    _, config_route = mock_github()

    await review_pull_request(event, github=github, llm=RoutingLLM({}), options=SECURITY_ONLY)

    assert config_route.calls.last.request.url.params["ref"] == BASE_SHA


@respx.mock
async def test_repo_config_selects_agents_ignores_paths_and_filters_severity(
    github: GitHubClient, event: PullRequestEvent
) -> None:
    reviews, _ = mock_github(
        repo_config="agents: [security]\nignore: ['app/settings.py']\nmin_severity: critical\n"
    )
    llm = RoutingLLM({"security": security_model, "performance": performance_model})

    await review_pull_request(event, github=github, llm=llm, options=ReviewOptions())

    assert {llm.agent_of(system) for system, _ in llm.calls} == {"security"}
    review = payload_of(reviews)
    assert anchors(review) == {("app/users.py", 11, 12)}  # settings.py ignored
    assert "`app/settings.py` (ignored by .reviewcrew.yml)" in review["body"]
    assert "settings from `.reviewcrew.yml`" in review["body"]
    assert "⚡ Performance" not in review["body"]


@respx.mock
async def test_invalid_repo_config_is_reported_and_defaults_are_used(
    github: GitHubClient, event: PullRequestEvent
) -> None:
    reviews, _ = mock_github(repo_config="agents: [security, linter]\nmax_comments: 500\n")

    await review_pull_request(
        event, github=github, llm=RoutingLLM({"security": security_model}), options=SECURITY_ONLY
    )

    body = payload_of(reviews)["body"]
    assert "⚠️ `.reviewcrew.yml` is invalid, so the default settings were used:" in body
    assert "`agents.1`" in body
    assert "`max_comments`" in body
    assert "| 🔒 Security | 2 | critical |" in body  # the review still ran with defaults


# --- token budget --------------------------------------------------------------------------


@respx.mock
async def test_token_budget_skips_remaining_chunks_and_says_so(
    github: GitHubClient, event: PullRequestEvent
) -> None:
    reviews, _ = mock_github()
    llm = RoutingLLM({"security": security_model})
    options = SECURITY_ONLY.model_copy(update={"token_budget": 10})  # too small for any call

    await review_pull_request(event, github=github, llm=llm, options=options)

    assert llm.calls == []
    body = payload_of(reviews)["body"]
    assert (
        "⏭️ The per-PR budget of 10 tokens was reached; 1 chunk not reviewed (security: 1)" in body
    )
    assert "| 🔒 Security | 0 | — | 0 |" in body
