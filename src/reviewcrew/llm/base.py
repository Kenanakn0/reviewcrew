"""Provider-agnostic interface for structured LLM completions."""

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel, ConfigDict

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class TokenUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


@dataclass(frozen=True)
class StructuredResponse[T]:
    value: T
    usage: TokenUsage
    model: str


class LLMError(Exception):
    """Base class for LLM failures."""


class LLMTransientError(LLMError):
    """Rate limits, timeouts, connection problems and 5xx responses: worth retrying."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMRequestError(LLMError):
    """The request itself was rejected (bad key, unknown model, invalid parameters)."""


class LLMOutputError(LLMError):
    """The model answered, but not with output matching the schema (invalid JSON, truncated,
    refused). The usage of the failed call is attached so budgets stay accurate."""

    def __init__(self, message: str, *, usage: TokenUsage | None = None) -> None:
        super().__init__(message)
        self.usage = usage or TokenUsage()


class LLMProvider(Protocol):
    """Anything that can turn a system + user prompt into a validated Pydantic model."""

    @property
    def name(self) -> str: ...

    async def complete_structured(
        self, *, system: str, user: str, schema: type[SchemaT]
    ) -> StructuredResponse[SchemaT]: ...
