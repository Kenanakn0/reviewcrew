import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa

from reviewcrew.github.auth import (
    InstallationToken,
    InstallationTokenProvider,
    create_app_jwt,
)
from reviewcrew.github.constants import API_VERSION
from tests.helpers import CLIENT_ID

API = "https://api.github.com"
TOKEN_URL = f"{API}/app/installations/42/access_tokens"
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _token_response(token: str, expires_at: datetime) -> httpx.Response:
    return httpx.Response(
        201, json={"token": token, "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")}
    )


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=API) as client:
        yield client


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def provider(
    http: httpx.AsyncClient, private_key_pem: str, clock: FakeClock
) -> InstallationTokenProvider:
    return InstallationTokenProvider(
        http, client_id=CLIENT_ID, private_key=private_key_pem, clock=clock
    )


def test_app_jwt_claims(private_key_pem: str, rsa_private_key: rsa.RSAPrivateKey) -> None:
    token = create_app_jwt(CLIENT_ID, private_key_pem, now=NOW)

    claims = jwt.decode(
        token,
        rsa_private_key.public_key(),
        algorithms=["RS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert jwt.get_unverified_header(token)["alg"] == "RS256"
    assert claims["iss"] == CLIENT_ID
    assert claims["iat"] == int((NOW - timedelta(seconds=60)).timestamp())
    # GitHub rejects JWTs whose lifetime exceeds 10 minutes.
    assert claims["exp"] - claims["iat"] <= 600
    assert claims["exp"] > int(NOW.timestamp())


def test_installation_token_repr_hides_token() -> None:
    token = InstallationToken(token="ghs_supersecret", expires_at=NOW)  # noqa: S106

    assert "ghs_supersecret" not in repr(token)


@respx.mock
async def test_token_request_uses_app_jwt(
    provider: InstallationTokenProvider, rsa_private_key: rsa.RSAPrivateKey
) -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=_token_response("ghs_one", NOW + timedelta(hours=1))
    )

    assert await provider.get_token(42) == "ghs_one"

    request = route.calls.last.request
    assert request.headers["X-GitHub-Api-Version"] == API_VERSION
    scheme, app_jwt = request.headers["Authorization"].split(" ")
    assert scheme == "Bearer"
    claims = jwt.decode(
        app_jwt,
        rsa_private_key.public_key(),
        algorithms=["RS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims["iss"] == CLIENT_ID


@respx.mock
async def test_token_is_cached_until_close_to_expiry(
    provider: InstallationTokenProvider, clock: FakeClock
) -> None:
    route = respx.post(TOKEN_URL).mock(
        side_effect=[
            _token_response("ghs_one", NOW + timedelta(hours=1)),
            _token_response("ghs_two", NOW + timedelta(hours=2)),
        ]
    )

    assert await provider.get_token(42) == "ghs_one"
    clock.now = NOW + timedelta(minutes=50)  # 10 minutes left: still outside the margin
    assert await provider.get_token(42) == "ghs_one"
    assert route.call_count == 1

    clock.now = NOW + timedelta(minutes=56)  # 4 minutes left: refresh
    assert await provider.get_token(42) == "ghs_two"
    assert route.call_count == 2


@respx.mock
async def test_tokens_are_cached_per_installation(provider: InstallationTokenProvider) -> None:
    respx.post(TOKEN_URL).mock(return_value=_token_response("ghs_a", NOW + timedelta(hours=1)))
    respx.post(f"{API}/app/installations/43/access_tokens").mock(
        return_value=_token_response("ghs_b", NOW + timedelta(hours=1))
    )

    assert await provider.get_token(42) == "ghs_a"
    assert await provider.get_token(43) == "ghs_b"


@respx.mock
async def test_concurrent_requests_fetch_a_single_token(
    provider: InstallationTokenProvider,
) -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=_token_response("ghs_one", NOW + timedelta(hours=1))
    )

    tokens = await asyncio.gather(*(provider.get_token(42) for _ in range(5)))

    assert tokens == ["ghs_one"] * 5
    assert route.call_count == 1


@respx.mock
async def test_token_request_failure_raises(provider: InstallationTokenProvider) -> None:
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(401, json={"message": "Bad JWT"}))

    with pytest.raises(httpx.HTTPStatusError):
        await provider.get_token(42)
