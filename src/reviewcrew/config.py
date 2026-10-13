"""Application settings loaded from environment variables and an optional `.env` file."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, FilePath, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Secrets must only ever come from the environment or `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    # GitHub App credentials (Settings -> Developer settings -> GitHub Apps -> your app).
    github_app_client_id: str = Field(min_length=1)
    github_private_key_path: FilePath
    github_webhook_secret: SecretStr = Field(min_length=1)
    github_api_url: HttpUrl = HttpUrl("https://api.github.com")
    github_timeout_seconds: float = Field(default=30.0, gt=0)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance (cached after the first call)."""
    return Settings()
