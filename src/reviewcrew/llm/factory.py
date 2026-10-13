"""Build the configured `LLMProvider` and own its HTTP client lifetime."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anthropic
import httpx

from reviewcrew.config import Settings
from reviewcrew.llm.anthropic_provider import AnthropicProvider
from reviewcrew.llm.base import LLMProvider
from reviewcrew.llm.openai_compat import OpenAICompatProvider


@asynccontextmanager
async def open_llm_provider(settings: Settings) -> AsyncIterator[LLMProvider]:
    if settings.llm_provider == "anthropic":
        api_key = settings.anthropic_api_key
        # Retries are handled uniformly by `with_retries`, so the SDK's own are disabled.
        async with anthropic.AsyncAnthropic(
            api_key=api_key.get_secret_value() if api_key else None,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        ) as client:
            yield AnthropicProvider(
                client,
                model=settings.llm_model,
                effort=settings.llm_effort,
                max_output_tokens=settings.llm_max_output_tokens,
                max_retries=settings.llm_max_retries,
                refusal_fallback=settings.anthropic_refusal_fallback,
            )
        return

    assert settings.openai_compat_base_url is not None  # noqa: S101 - enforced by Settings
    headers = {}
    if settings.openai_compat_api_key is not None:
        headers["Authorization"] = f"Bearer {settings.openai_compat_api_key.get_secret_value()}"
    async with httpx.AsyncClient(
        base_url=str(settings.openai_compat_base_url),
        headers=headers,
        timeout=settings.llm_timeout_seconds,
    ) as http:
        yield OpenAICompatProvider(
            http,
            model=settings.llm_model,
            max_output_tokens=settings.llm_max_output_tokens,
            max_retries=settings.llm_max_retries,
        )
