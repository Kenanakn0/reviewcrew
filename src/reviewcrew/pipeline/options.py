"""Tunables for one review run."""

from pydantic import BaseModel, ConfigDict, Field

from reviewcrew.diff.processor import DiffOptions
from reviewcrew.pipeline.aggregator import AggregationConfig


class ReviewOptions(BaseModel):
    model_config = ConfigDict(frozen=True)

    diff: DiffOptions = DiffOptions()
    aggregation: AggregationConfig = AggregationConfig()
    max_inline_comments: int = Field(default=20, ge=0)
    agent_timeout_seconds: float = Field(default=600.0, gt=0)
    max_concurrent_llm_calls: int = Field(default=4, ge=1)
