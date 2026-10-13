"""Application settings loaded from environment variables and an optional `.env` file."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, FilePath, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from reviewcrew.diff.chunker import MIN_CHUNK_TOKENS
from reviewcrew.diff.filters import FilterConfig
from reviewcrew.diff.processor import DiffOptions
from reviewcrew.llm.anthropic_provider import Effort


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

    # LLM.
    llm_provider: Literal["anthropic", "openai_compat"] = "anthropic"
    llm_model: str = Field(default="claude-opus-5-5", min_length=1)
    llm_effort: Effort = "high"  # Anthropic only: depth of reasoning vs. token spend
    llm_max_output_tokens: int = Field(default=16000, ge=256)
    llm_timeout_seconds: float = Field(default=300.0, gt=0)
    llm_max_retries: int = Field(default=3, ge=0)
    # Optional: the Anthropic SDK also finds ANTHROPIC_API_KEY in the process environment.
    anthropic_api_key: SecretStr | None = None
    anthropic_refusal_fallback: bool = True
    # e.g. http://localhost:11434/v1 for Ollama.
    openai_compat_base_url: HttpUrl | None = None
    openai_compat_api_key: SecretStr | None = None

    # Review output.
    review_language: Literal["en", "tr"] = "en"

    @model_validator(mode="after")
    def _check_llm_provider(self) -> Self:
        if self.llm_provider == "openai_compat" and self.openai_compat_base_url is None:
            raise ValueError("OPENAI_COMPAT_BASE_URL is required when LLM_PROVIDER=openai_compat")
        return self

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
