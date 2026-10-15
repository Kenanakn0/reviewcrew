"""OpenAI-compatible `/chat/completions` endpoints (e.g. Ollama for free local testing)."""

import logging
import re
import time
from typing import Any

import httpx
import pydantic

from reviewcrew.llm.base import (
    LLMOutputError,
    LLMRequestError,
    LLMTransientError,
    SchemaT,
    StructuredResponse,
    TokenUsage,
)
from reviewcrew.llm.retry import with_retries
from reviewcrew.llm.schema import strict_json_schema

logger = logging.getLogger(__name__)

_TRANSIENT_STATUS = frozenset({408, 409, 429})
_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(?P<body>.*?)\n?```\s*$", re.DOTALL)


def extract_json_object(text: str) -> str:
    """The JSON object in a reply, tolerating Markdown fences or surrounding prose.

    Endpoints that enforce the schema return bare JSON; smaller local models sometimes
    still wrap it, which would otherwise cost a retry.
    """
    stripped = text.strip()
    fenced = _FENCE.match(stripped)
    if fenced:
        stripped = fenced.group("body").strip()
    if stripped.startswith("{"):
        return stripped
    start, end = stripped.find("{"), stripped.rfind("}")
    return stripped[start : end + 1] if 0 <= start < end else stripped


class _Message(pydantic.BaseModel):
    content: str | None = None
    refusal: str | None = None


class _Choice(pydantic.BaseModel):
    message: _Message
    finish_reason: str | None = None


class _Usage(pydantic.BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0


class _ChatCompletion(pydantic.BaseModel):
    model: str = ""
    choices: list[_Choice]
    usage: _Usage = _Usage()


class OpenAICompatProvider:
    """`http` must be created with the endpoint's base URL, timeout and auth header."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        model: str,
        max_output_tokens: int,
        max_retries: int,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._http = http
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay

    @property
    def name(self) -> str:
        return f"openai_compat:{self._model}"

    async def complete_structured(
        self, *, system: str, user: str, schema: type[SchemaT]
    ) -> StructuredResponse[SchemaT]:
        return await with_retries(
            lambda: self._complete_once(system=system, user=user, schema=schema),
            max_retries=self._max_retries,
            base_delay=self._retry_base_delay,
            description=f"OpenAI-compatible request ({self._model})",
        )

    async def _complete_once(
        self, *, system: str, user: str, schema: type[SchemaT]
    ) -> StructuredResponse[SchemaT]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": self._max_output_tokens,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": strict_json_schema(schema),
                    "strict": True,
                },
            },
        }
        started = time.monotonic()
        try:
            response = await self._http.post("chat/completions", json=payload)
        except httpx.TransportError as exc:  # timeouts and connection failures
            raise LLMTransientError(f"{type(exc).__name__}: {exc}") from exc
        if response.status_code in _TRANSIENT_STATUS or response.status_code >= 500:
            retry_after = response.headers.get("retry-after")
            raise LLMTransientError(
                f"HTTP {response.status_code}",
                retry_after=float(retry_after) if retry_after and retry_after.isdigit() else None,
            )
        if response.is_error:
            raise LLMRequestError(f"HTTP {response.status_code}: {response.text[:300]}")

        try:
            completion = _ChatCompletion.model_validate_json(response.content)
        except pydantic.ValidationError as exc:
            raise LLMRequestError(f"unexpected response shape: {exc}") from exc
        usage = TokenUsage(
            input_tokens=completion.usage.prompt_tokens,
            output_tokens=completion.usage.completion_tokens,
        )
        logger.info(
            "LLM call model=%s finish=%s input_tokens=%d output_tokens=%d duration=%.1fs",
            completion.model or self._model,
            completion.choices[0].finish_reason if completion.choices else None,
            usage.input_tokens,
            usage.output_tokens,
            time.monotonic() - started,
        )
        if not completion.choices:
            raise LLMOutputError("response had no choices", usage=usage)
        choice = completion.choices[0]
        if choice.message.refusal:
            raise LLMOutputError("model refused", usage=usage)
        if choice.finish_reason == "length":
            raise LLMOutputError("output truncated at max_tokens", usage=usage)
        try:
            value = schema.model_validate_json(extract_json_object(choice.message.content or ""))
        except pydantic.ValidationError as exc:
            raise LLMOutputError(
                f"response did not match {schema.__name__}: {exc}", usage=usage
            ) from exc
        return StructuredResponse(value=value, usage=usage, model=completion.model or self._model)
