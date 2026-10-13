"""Queue and worker: Redis is fakeredis; the arq worker and our job code are real."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import arq.worker
import fakeredis
import httpx
import pytest
import respx
from arq import ArqRedis, Worker

from reviewcrew import worker as worker_module
from reviewcrew.config import Settings
from reviewcrew.github.auth import InstallationTokenProvider
from reviewcrew.github.client import GitHubClient
from reviewcrew.jobs import ReviewClaims, enqueue_review, review_key
from reviewcrew.main import create_app
from reviewcrew.pipeline.options import ReviewOptions
from reviewcrew.webhook.events import PullRequestEvent
from reviewcrew.webhook.signature import compute_signature
from reviewcrew.worker import WorkerSettings, review_pull_request_job, shutdown, startup
from tests.fakes import RoutingLLM
from tests.helpers import CLIENT_ID, WEBHOOK_SECRET, pull_request_payload
from tests.test_review_pipeline import REPO, mock_github, security_model

TTL = 3600


@pytest.fixture
async def pool() -> AsyncIterator[ArqRedis]:
    fake = fakeredis.FakeAsyncRedis()
    redis = ArqRedis(connection_pool=fake.connection_pool)
    yield redis
    await redis.aclose()


@pytest.fixture
def claims(pool: ArqRedis) -> ReviewClaims:
    return ReviewClaims(pool, ttl_seconds=TTL)


@pytest.fixture
def event() -> PullRequestEvent:
    return PullRequestEvent.model_validate(pull_request_payload(repo=REPO))


def test_review_key_identifies_the_commit(event: PullRequestEvent) -> None:
    assert review_key(event) == "octo/demo#7@abc123"


async def test_claims_are_atomic_and_releasable(claims: ReviewClaims, pool: ArqRedis) -> None:
    assert await claims.claim("k")
    assert not await claims.claim("k")
    await claims.complete("k")
    assert not await claims.claim("k")
    assert 0 < await pool.ttl("reviewcrew:reviewed:k") <= TTL
    await claims.release("k")
    assert await claims.claim("k")


async def test_enqueue_deduplicates_while_queued(
    pool: ArqRedis, claims: ReviewClaims, event: PullRequestEvent
) -> None:
    assert await enqueue_review(pool, claims, event) == "queued"
    assert await enqueue_review(pool, claims, event) == "duplicate"
    assert await pool.zcard("arq:queue") == 1


async def test_enqueue_skips_commits_already_reviewed(
    pool: ArqRedis, claims: ReviewClaims, event: PullRequestEvent
) -> None:
    await claims.complete(review_key(event))

    assert await enqueue_review(pool, claims, event) == "duplicate"
    assert await pool.zcard("arq:queue") == 0


async def test_a_new_commit_is_a_new_review(
    pool: ArqRedis, claims: ReviewClaims, event: PullRequestEvent
) -> None:
    await claims.complete(review_key(event))
    payload = pull_request_payload(repo=REPO, action="synchronize")
    payload["pull_request"]["head"]["sha"] = "fff999"

    assert await enqueue_review(pool, claims, PullRequestEvent.model_validate(payload)) == "queued"


# --- the job function -----------------------------------------------------------------------


class Recorder:
    def __init__(self, error: BaseException | None = None) -> None:
        self.calls = 0
        self.error = error

    async def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


def job_ctx(claims: ReviewClaims) -> dict[str, Any]:
    return {"claims": claims, "github": object(), "llm": object(), "options": ReviewOptions()}


async def test_job_reviews_once_per_commit(
    claims: ReviewClaims, event: PullRequestEvent, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = Recorder()
    monkeypatch.setattr(worker_module, "review_pull_request", review)
    payload = event.model_dump(mode="json")

    first = await review_pull_request_job(job_ctx(claims), payload)
    second = await review_pull_request_job(job_ctx(claims), payload)

    assert (first, second) == ("reviewed", "duplicate")
    assert review.calls == 1


@pytest.mark.parametrize("error", [RuntimeError("github down"), asyncio.CancelledError()])
async def test_failed_or_cancelled_job_releases_the_claim(
    claims: ReviewClaims,
    event: PullRequestEvent,
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
) -> None:
    monkeypatch.setattr(worker_module, "review_pull_request", Recorder(error))

    with pytest.raises(type(error)):
        await review_pull_request_job(job_ctx(claims), event.model_dump(mode="json"))

    assert await claims.claim(review_key(event))  # free again: a redelivery can retry


# --- acceptance: the same webhook twice yields one review -----------------------------------


@respx.mock
async def test_same_webhook_twice_produces_a_single_review(
    settings: Settings,
    pool: ArqRedis,
    claims: ReviewClaims,
    private_key_pem: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(arq.worker, "log_redis_info", _no_redis_info)  # INFO isn't in fakeredis
    reviews, _ = mock_github()
    app = create_app(settings, dispatch=lambda e: enqueue_review(pool, claims, e))
    body = json.dumps(pull_request_payload(repo=REPO)).encode()
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": compute_signature(WEBHOOK_SECRET.encode(), body),
    }

    async with (
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
        httpx.AsyncClient(base_url="https://api.github.com") as github_http,
    ):
        first = await client.post("/webhook", content=body, headers=headers)
        redelivered = await client.post("/webhook", content=body, headers=headers)

        tokens = InstallationTokenProvider(
            github_http, client_id=CLIENT_ID, private_key=private_key_pem
        )
        worker = Worker(
            functions=WorkerSettings.functions,
            redis_pool=pool,
            burst=True,
            poll_delay=0.01,
            keep_result=WorkerSettings.keep_result,
            handle_signals=False,
            ctx={
                "claims": claims,
                "github": GitHubClient(github_http, tokens),
                "llm": RoutingLLM({"security": security_model}),
                "options": ReviewOptions(agents=("security",)),
            },
        )
        await worker.main()
        after_review = await client.post("/webhook", content=body, headers=headers)

    assert (first.status_code, first.json()["status"]) == (202, "accepted")
    assert (redelivered.status_code, redelivered.json()["status"]) == (200, "duplicate")
    assert (worker.jobs_complete, worker.jobs_failed) == (1, 0)
    assert reviews.call_count == 1
    assert after_review.json()["status"] == "duplicate"


async def _no_redis_info(*args: Any, **kwargs: Any) -> None:
    return None


# --- worker lifecycle ------------------------------------------------------------------------


async def test_worker_startup_and_shutdown(settings: Settings, pool: ArqRedis) -> None:
    ctx: dict[str, Any] = {"settings": settings, "redis": pool}

    await startup(ctx)
    try:
        assert isinstance(ctx["github"], GitHubClient)
        assert ctx["llm"].name == "anthropic:claude-opus-5-5"
        assert ctx["options"].agents == ("security", "performance", "tests")
        assert isinstance(ctx["claims"], ReviewClaims)
    finally:
        await shutdown(ctx)


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.github.com/x")
    return httpx.HTTPStatusError(
        "error", request=request, response=httpx.Response(status, request=request)
    )


@pytest.mark.parametrize(
    "error",
    [_status_error(502), _status_error(429), httpx.ConnectError("reset")],
)
async def test_transient_github_errors_are_retried_later(
    claims: ReviewClaims,
    event: PullRequestEvent,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    monkeypatch.setattr(worker_module, "review_pull_request", Recorder(error))
    ctx = job_ctx(claims) | {"job_try": 2}

    with pytest.raises(arq.Retry) as retry:
        await review_pull_request_job(ctx, event.model_dump(mode="json"))

    assert retry.value.defer_score == 2 * worker_module.RETRY_BASE_DELAY_SECONDS * 1000
    assert await claims.claim(review_key(event))  # released for the retry


async def test_permanent_github_errors_are_not_retried(
    claims: ReviewClaims, event: PullRequestEvent, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker_module, "review_pull_request", Recorder(_status_error(404)))

    with pytest.raises(httpx.HTTPStatusError):
        await review_pull_request_job(job_ctx(claims), event.model_dump(mode="json"))
