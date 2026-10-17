"""Application settings loaded from environment variables and an optional `.env` file."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import (
    Field,
    FilePath,
    HttpUrl,
    RedisDsn,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from reviewcrew.agents.models import AgentName
from reviewcrew.diff.chunker import MIN_CHUNK_TOKENS
from reviewcrew.diff.filters import FilterConfig
from reviewcrew.diff.processor import DiffOptions
from reviewcrew.llm.anthropic_provider import Effort
from reviewcrew.pipeline.aggregator import AggregationConfig
from reviewcrew.pipeline.options import ReviewOptions

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"


def _all_agents() -> list[AgentName]:
    return ["security", "performance", "tests"]


class CoreSettings(BaseSettings):
    """Everything a review needs besides GitHub and the queue: diff handling, the LLM and
    review policy. The evaluation runner uses this alone (no GitHub App required)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    diff_max_tokens_per_chunk: int = Field(default=8000, ge=MIN_CHUNK_TOKENS)
    diff_max_changed_lines_per_file: int = Field(default=1000, ge=1)
    diff_context_lines: int = Field(default=5, ge=0)

    # "openai_compat" covers any OpenAI-compatible endpoint, e.g. a local Ollama.
    llm_provider: Literal["anthropic", "openai_compat"] = "anthropic"
    # Defaults to DEFAULT_ANTHROPIC_MODEL for Anthropic; required for openai_compat.
    llm_model: str = ""
    llm_effort: Effort = "high"  # Anthropic only: depth of reasoning vs. token spend
    llm_max_output_tokens: int = Field(default=16000, ge=256)
    llm_timeout_seconds: float = Field(default=300.0, gt=0)
    llm_max_retries: int = Field(default=3, ge=0)
    # Only used with LLM_PROVIDER=anthropic (the SDK also finds ANTHROPIC_API_KEY itself).
    anthropic_api_key: SecretStr | None = None
    anthropic_refusal_fallback: bool = True
    # e.g. http://localhost:11434/v1 for Ollama.
    openai_compat_base_url: HttpUrl | None = None
    openai_compat_api_key: SecretStr | None = None

    llm_max_concurrency: int = Field(default=4, ge=1)  # simultaneous LLM calls per review

    # JSON list in the environment, e.g. REVIEW_AGENTS='["security", "tests"]'.
    review_agents: list[AgentName] = Field(default_factory=_all_agents, min_length=1)
    review_language: Literal["en", "tr"] = "en"
    review_min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    review_max_inline_comments: int = Field(default=20, ge=0)
    review_agent_timeout_seconds: float = Field(default=600.0, gt=0)
    # Tokens one PR may spend across all agents; remaining chunks are skipped beyond it.
    review_token_budget: int | None = Field(default=300_000, ge=1)

    def review_options(self) -> ReviewOptions:
        return ReviewOptions(
            agents=tuple(dict.fromkeys(self.review_agents)),
            language=self.review_language,
            token_budget=self.review_token_budget,
            diff=self.diff_options(),
            aggregation=AggregationConfig(min_confidence=self.review_min_confidence),
            max_inline_comments=self.review_max_inline_comments,
            agent_timeout_seconds=self.review_agent_timeout_seconds,
            max_concurrent_llm_calls=self.llm_max_concurrency,
        )

    def diff_options(self) -> DiffOptions:
        return DiffOptions(
            filters=FilterConfig(max_changed_lines=self.diff_max_changed_lines_per_file),
            max_tokens_per_chunk=self.diff_max_tokens_per_chunk,
            context_lines=self.diff_context_lines,
        )

    @field_validator(
        "anthropic_api_key", "openai_compat_base_url", "openai_compat_api_key", mode="before"
    )
    @classmethod
    def _empty_means_unset(cls, value: object) -> object:
        # `KEY=` in .env (or an empty variable passed through Docker Compose) means "not set".
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _check_llm_provider(self) -> Self:
        if self.llm_provider == "openai_compat":
            if self.openai_compat_base_url is None:
                raise ValueError(
                    "OPENAI_COMPAT_BASE_URL is required when LLM_PROVIDER=openai_compat"
                )
            if not self.llm_model.strip():
                raise ValueError(
                    "LLM_MODEL is required when LLM_PROVIDER=openai_compat "
                    "(e.g. qwen2.5-coder:7b for Ollama)"
                )
        elif not self.llm_model.strip():
            self.llm_model = DEFAULT_ANTHROPIC_MODEL
        return self


class Settings(CoreSettings):
    """Full runtime configuration of the API and the worker. Secrets must only ever come
    from the environment or `.env`."""

    app_env: Literal["development", "test", "production"] = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    # GitHub App credentials (Settings -> Developer settings -> GitHub Apps -> your app).
    github_app_client_id: str = Field(min_length=1)
    github_private_key_path: FilePath
    github_webhook_secret: SecretStr = Field(min_length=1)
    github_api_url: HttpUrl = HttpUrl("https://api.github.com")
    github_timeout_seconds: float = Field(default=30.0, gt=0)

    redis_url: RedisDsn = RedisDsn("redis://localhost:6379/0")
    # How long a reviewed (repo, PR, head SHA) is remembered to suppress duplicates.
    review_dedup_ttl_seconds: int = Field(default=7 * 24 * 3600, ge=60)
    review_job_timeout_seconds: float = Field(default=1800.0, gt=0)
    worker_max_jobs: int = Field(default=4, ge=1)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance (cached after the first call)."""
    return Settings()
