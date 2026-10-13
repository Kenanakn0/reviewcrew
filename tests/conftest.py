from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

from reviewcrew.config import Settings, get_settings
from tests.helpers import CLIENT_ID, WEBHOOK_SECRET


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Keep the cached settings from leaking between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def rsa_private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def private_key_pem(rsa_private_key: rsa.RSAPrivateKey) -> str:
    return rsa_private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


@pytest.fixture
def private_key_path(tmp_path: Path, private_key_pem: str) -> Path:
    path = tmp_path / "app.pem"
    path.write_text(private_key_pem, encoding="utf-8")
    return path


@pytest.fixture
def settings(private_key_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        github_app_client_id=CLIENT_ID,
        github_private_key_path=private_key_path,
        github_webhook_secret=SecretStr(WEBHOOK_SECRET),
    )
