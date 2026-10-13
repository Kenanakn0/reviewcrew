"""GitHub App authentication: App JWT -> cached installation access tokens."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
import jwt
from pydantic import BaseModel

from reviewcrew.github.constants import API_VERSION, JSON_MEDIA_TYPE

logger = logging.getLogger(__name__)

# GitHub rejects App JWTs that expire more than 10 minutes after they were issued.
JWT_LIFETIME = timedelta(minutes=9)
# Backdate `iat` to tolerate clock drift between us and GitHub.
JWT_CLOCK_SKEW = timedelta(seconds=60)
# Refresh an installation token this long before it actually expires.
TOKEN_REFRESH_MARGIN = timedelta(minutes=5)

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def create_app_jwt(client_id: str, private_key: str, *, now: datetime) -> str:
    """Create the short-lived RS256 JWT that authenticates as the GitHub App itself."""
    issued_at = now - JWT_CLOCK_SKEW
    payload = {
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + JWT_LIFETIME).timestamp()),
        "iss": client_id,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


class _AccessTokenResponse(BaseModel):
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class InstallationToken:
    token: str = field(repr=False)
    expires_at: datetime


class InstallationTokenProvider:
    """Hands out installation tokens, reusing each one until it is close to expiry."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        client_id: str,
        private_key: str,
        clock: Clock = _utcnow,
    ) -> None:
        self._http = http
        self._client_id = client_id
        self._private_key = private_key
        self._clock = clock
        self._cache: dict[int, InstallationToken] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    async def get_token(self, installation_id: int) -> str:
        lock = self._locks.setdefault(installation_id, asyncio.Lock())
        async with lock:
            cached = self._cache.get(installation_id)
            if cached is not None and cached.expires_at - self._clock() > TOKEN_REFRESH_MARGIN:
                return cached.token
            fresh = await self._request_token(installation_id)
            self._cache[installation_id] = fresh
            return fresh.token

    async def _request_token(self, installation_id: int) -> InstallationToken:
        app_jwt = create_app_jwt(self._client_id, self._private_key, now=self._clock())
        response = await self._http.post(
            f"/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": JSON_MEDIA_TYPE,
                "X-GitHub-Api-Version": API_VERSION,
            },
        )
        response.raise_for_status()
        body = _AccessTokenResponse.model_validate_json(response.content)
        logger.info(
            "Issued installation token for installation %s (expires %s)",
            installation_id,
            body.expires_at.isoformat(),
        )
        return InstallationToken(token=body.token, expires_at=body.expires_at)
