from pathlib import Path

import pytest
from pydantic import ValidationError

from reviewcrew.config import Settings, get_settings


@pytest.fixture
def required_env(monkeypatch: pytest.MonkeyPatch, private_key_path: Path) -> None:
    for name in ("APP_ENV", "LOG_LEVEL", "HOST", "PORT", "GITHUB_API_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GITHUB_APP_CLIENT_ID", "Iv23liExample")
    monkeypatch.setenv("GITHUB_PRIVATE_KEY_PATH", str(private_key_path))
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "shh")


@pytest.mark.usefixtures("required_env")
def test_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.log_level == "INFO"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert str(settings.github_api_url) == "https://api.github.com/"


@pytest.mark.usefixtures("required_env")
def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("PORT", "9000")

    settings = Settings(_env_file=None)

    assert settings.app_env == "production"
    assert settings.log_level == "DEBUG"
    assert settings.port == 9000


@pytest.mark.usefixtures("required_env")
def test_env_file_is_read(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("LOG_LEVEL=WARNING\n", encoding="utf-8")

    settings = Settings(_env_file=env_file)

    assert settings.log_level == "WARNING"


@pytest.mark.usefixtures("required_env")
def test_webhook_secret_is_masked_in_repr() -> None:
    settings = Settings(_env_file=None)

    assert "shh" not in repr(settings)
    assert settings.github_webhook_secret.get_secret_value() == "shh"


@pytest.mark.usefixtures("required_env")
@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("LOG_LEVEL", "LOUD"),
        ("PORT", "70000"),
        ("GITHUB_WEBHOOK_SECRET", ""),
        ("GITHUB_PRIVATE_KEY_PATH", "does/not/exist.pem"),
    ],
)
def test_invalid_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.usefixtures("required_env")
@pytest.mark.parametrize("missing", ["GITHUB_APP_CLIENT_ID", "GITHUB_WEBHOOK_SECRET"])
def test_github_credentials_are_required(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    monkeypatch.delenv(missing)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.usefixtures("required_env")
def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
