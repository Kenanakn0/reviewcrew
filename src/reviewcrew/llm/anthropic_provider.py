"""Claude via the official Anthropic SDK, using structured outputs (`messages.parse`)."""

import logging
import time
from typing import Literal

import anthropic
import pydantic
from anthropic.types.anthropic_beta_param import AnthropicBetaParam

from reviewcrew.llm.base import (
    LLMOutputError,
    LLMRequestError,
    LLMTransientError,
    SchemaT,
    StructuredResponse,
    TokenUsage,
)
from reviewcrew.llm.retry import with_retries

logger = logging.getLogger(__name__)

Effort = Literal["low", "medium", "high", "xhigh", "max"]

# Models that accept the server-side refusal fallback (`fallbacks="default"`). Reviewing
# security-sensitive code can trip safety classifiers; the fallback retries the same request
# on a model chosen by the API instead of returning nothing.
REFUSAL_FALLBACK_MODELS = frozenset(
    {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
)
REFUSAL_FALLBACK_BETA: AnthropicBetaParam = "server-side-fallback-2026-07-01"
_TRANSIENT_STATUS = frozenset({408, 409, 429})


class AnthropicProvider:
    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        *,
        model: str,
        effort: Effort,
        max_output_tokens: int,
        max_retries: int,
        retry_base_delay: float = 1.0,
        refusal_fallback: bool = True,
    ) -> None:
        self._client = client
        self._model = model
        self._effort: Effort = effort
        self._max_output_tokens = max_output_tokens
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._use_fallback = refusal_fallback and model in REFUSAL_FALLBACK_MODELS

    @property
    def name(self) -> str:
        return f"anthropic:{self._model}"

    async def complete_structured(
        self, *, system: str, user: str, schema: type[SchemaT]
    ) -> StructuredResponse[SchemaT]:
        return await with_retries(
            lambda: self._complete_once(system=system, user=user, schema=schema),
            max_retries=self._max_retries,
            base_delay=self._retry_base_delay,
            description=f"Anthropic request ({self._model})",
        )

    async def _complete_once(
        self, *, system: str, user: str, schema: type[SchemaT]
    ) -> StructuredResponse[SchemaT]:
        started = time.monotonic()
        # `create` + our own validation rather than `parse`: `parse` validates before we can
        # look at `stop_reason`, which would hide refusals/truncation and lose token usage.
        try:
            response = await self._client.beta.messages.create(
                model=self._model,
                max_tokens=self._max_output_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={
                    "effort": self._effort,
                    "format": {"type": "json_schema", "schema": anthropic.transform_schema(schema)},
                },
                betas=[REFUSAL_FALLBACK_BETA] if self._use_fallback else anthropic.omit,
                fallbacks="default" if self._use_fallback else anthropic.omit,
            )
        except anthropic.APIConnectionError as exc:  # includes APITimeoutError
            raise LLMTransientError(f"connection error: {exc}") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code in _TRANSIENT_STATUS or exc.status_code >= 500:
                raise LLMTransientError(
                    f"HTTP {exc.status_code}", retry_after=_retry_after(exc)
                ) from exc
            raise LLMRequestError(f"HTTP {exc.status_code}: {exc.message}") from exc

        usage = TokenUsage(
            input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens
        )
        logger.info(
            "LLM call model=%s stop=%s input_tokens=%d output_tokens=%d duration=%.1fs",
            response.model,
            response.stop_reason,
            usage.input_tokens,
            usage.output_tokens,
            time.monotonic() - started,
        )
        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise LLMOutputError(f"model refused (category={category})", usage=usage)
        if response.stop_reason == "max_tokens":
            raise LLMOutputError("output truncated at max_tokens", usage=usage)
        # With a refusal fallback the content can hold the declined model's text, a
        # `fallback` block, then the answer; the structured output is the last text block.
        texts = [block.text for block in response.content if block.type == "text"]
        if not texts:
            raise LLMOutputError("response contained no structured output", usage=usage)
        try:
            value = schema.model_validate_json(texts[-1])
        except pydantic.ValidationError as exc:
            raise LLMOutputError(
                f"response did not match {schema.__name__}: {exc}", usage=usage
            ) from exc
        return StructuredResponse(value=value, usage=usage, model=str(response.model))


def _retry_after(exc: anthropic.APIStatusError) -> float | None:
    value = exc.response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
