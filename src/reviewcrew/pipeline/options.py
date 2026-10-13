"""Tunables for one review run: server defaults, refined by the repository's config."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from reviewcrew.agents.models import AgentName
from reviewcrew.diff.processor import DiffOptions
from reviewcrew.pipeline.aggregator import AggregationConfig
from reviewcrew.repo_config.schema import RepoConfig


class ReviewOptions(BaseModel):
    model_config = ConfigDict(frozen=True)

    agents: tuple[AgentName, ...] = ("security", "performance", "tests")
    language: Literal["en", "tr"] = "en"
    diff: DiffOptions = DiffOptions()
    aggregation: AggregationConfig = AggregationConfig()
    max_inline_comments: int = Field(default=20, ge=0)
    agent_timeout_seconds: float = Field(default=600.0, gt=0)
    max_concurrent_llm_calls: int = Field(default=4, ge=1)
    token_budget: int | None = Field(default=None, ge=1)  # per PR; None = unlimited

    def with_repo_config(self, config: RepoConfig) -> "ReviewOptions":
        """Apply `.reviewcrew.yml`. Cost and safety limits (budget, timeouts, confidence
        threshold) stay under the server's control."""
        filters = self.diff.filters.model_copy(
            update={"ignore_globs": self.diff.filters.ignore_globs + config.ignore}
        )
        return self.model_copy(
            update={
                "agents": config.agents or self.agents,
                "language": config.language or self.language,
                "diff": self.diff.model_copy(update={"filters": filters}),
                "aggregation": self.aggregation.model_copy(
                    update={"min_severity": config.min_severity}
                ),
                "max_inline_comments": (
                    config.max_comments
                    if config.max_comments is not None
                    else self.max_inline_comments
                ),
            }
        )
