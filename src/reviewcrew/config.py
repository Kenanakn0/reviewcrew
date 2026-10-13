"""Application settings loaded from environment variables and an optional `.env` file."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, FilePath, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from reviewcrew.diff.chunker import MIN_CHUNK_TOKENS
from reviewcrew.diff.filters import FilterConfig
from reviewcrew.diff.processor import DiffOptions


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

    # Diff processing.
    diff_max_tokens_per_chunk: int = Field(default=8000, ge=MIN_CHUNK_TOKENS)
    diff_max_changed_lines_per_file: int = Field(default=1000, ge=1)
    diff_context_lines: int = Field(default=5, ge=0)

    def diff_options(self) -> DiffOptions:
        return DiffOptions(
            filters=FilterConfig(max_changed_lines=self.diff_max_changed_lines_per_file),
            max_tokens_per_chunk=self.diff_max_tokens_per_chunk,
            context_lines=self.diff_context_lines,
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance (cached after the first call)."""
    return Settings()
