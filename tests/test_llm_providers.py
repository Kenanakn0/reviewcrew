"""Provider tests at the HTTP boundary.

The Anthropic SDK (1.x) runs on `httpx2`, which `respx` cannot see, so its traffic is served
by an `httpx2.MockTransport`. The OpenAI-compatible provider uses `httpx` and `respx`.
"""

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import anthropic
import httpx
import httpx2
import pytest
import respx

from reviewcrew.agents.models import AgentReport
from reviewcrew.llm.anthropic_provider import REFUSAL_FALLBACK_BETA, AnthropicProvider
from reviewcrew.llm.base import LLMOutputError, LLMRequestError, LLMTransientError
from reviewcrew.llm.openai_compat import OpenAICompatProvider

REPORT = {
    "findings": [
        {
            "path": "app/users.py",
            "line": 11,
            "end_line": None,
            "severity": "high",
            "confidence": 0.95,
            "title": "SQL injection",
            "explanation": "User input is interpolated into SQL.",
            "suggestion": "Use a parameterised query.",
        }
    ]
}

Handler = Callable[[httpx2.Request], httpx2.Response]


def _message(text: str, *, stop_reason: str = "end_turn", **extra: Any) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 80},
        **extra,
    }


class AnthropicServer:
    """Scripted responses for the SDK; records every request it receives."""

    def __init__(self, responses: list[httpx2.Response]) -> None:
        self.responses = responses
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.responses[min(len(self.requests), len(self.responses)) - 1]

    def body(self, index: int = -1) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(self.requests[index].content)
        return result


def _anthropic(server: AnthropicServer, *, model: str = "claude-opus-5-5") -> AnthropicProvider:
    client = anthropic.AsyncAnthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(server)),
    )
    return AnthropicProvider(
        client,
        model=model,
        effort="high",
        max_output_tokens=4000,
        max_retries=2,
        retry_base_delay=0,
    )


async def test_anthropic_returns_parsed_report_and_usage() -> None:
    server = AnthropicServer([httpx2.Response(200, json=_message(json.dumps(REPORT)))])

    result = await _anthropic(server).complete_structured(
        system="sys", user="diff", schema=AgentReport
    )

    assert result.value.findings[0].line == 11
    assert result.usage.input_tokens == 1200
    assert result.usage.output_tokens == 80
    body = server.body()
    assert body["model"] == "claude-opus-5-5"
    assert body["system"] == "sys"
    assert body["messages"] == [{"role": "user", "content": "diff"}]
    assert body["output_config"]["effort"] == "high"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default"
    assert REFUSAL_FALLBACK_BETA in server.requests[-1].headers["anthropic-beta"]


async def test_anthropic_omits_fallback_for_models_without_it() -> None:
    server = AnthropicServer([httpx2.Response(200, json=_message(json.dumps(REPORT)))])

    await _anthropic(server, model="claude-haiku-5-5").complete_structured(
        system="s", user="u", schema=AgentReport
    )

    assert "fallbacks" not in server.body()
    assert "anthropic-beta" not in server.requests[-1].headers


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_message("not json"), "did not match"),
        (_message('{"findings": "none"}'), "did not match"),
        (_message("", stop_reason="refusal", stop_details=None), "refused"),
        (_message('{"findings": [', stop_reason="max_tokens"), "truncated"),
    ],
)
async def test_anthropic_bad_output_raises_output_error(
    response: dict[str, Any], message: str
) -> None:
    server = AnthropicServer([httpx2.Response(200, json=response)])

    with pytest.raises(LLMOutputError, match=message):
        await _anthropic(server).complete_structured(system="s", user="u", schema=AgentReport)

    assert len(server.requests) == 1  # output errors are the agent's to retry, not ours


async def test_anthropic_refusal_keeps_token_usage() -> None:
    server = AnthropicServer([httpx2.Response(200, json=_message("", stop_reason="refusal"))])

    with pytest.raises(LLMOutputError) as caught:
        await _anthropic(server).complete_structured(system="s", user="u", schema=AgentReport)

    assert caught.value.usage.total_tokens == 1280


async def test_anthropic_uses_last_text_block() -> None:
    message = _message(json.dumps(REPORT))
    message["content"].insert(0, {"type": "text", "text": "partial answer from a declined model"})
    server = AnthropicServer([httpx2.Response(200, json=message)])

    result = await _anthropic(server).complete_structured(system="s", user="u", schema=AgentReport)

    assert len(result.value.findings) == 1


async def test_anthropic_rate_limit_is_retried() -> None:
    server = AnthropicServer(
        [
            httpx2.Response(429, headers={"retry-after": "0"}, json={"type": "error"}),
            httpx2.Response(529, json={"type": "error"}),
            httpx2.Response(200, json=_message(json.dumps(REPORT))),
        ]
    )

    result = await _anthropic(server).complete_structured(system="s", user="u", schema=AgentReport)

    assert len(result.value.findings) == 1
    assert len(server.requests) == 3


async def test_anthropic_persistent_server_errors_surface_as_transient() -> None:
    server = AnthropicServer([httpx2.Response(500, json={"type": "error"})])

    with pytest.raises(LLMTransientError):
        await _anthropic(server).complete_structured(system="s", user="u", schema=AgentReport)

    assert len(server.requests) == 3  # 1 + max_retries


async def test_anthropic_client_errors_are_not_retried() -> None:
    server = AnthropicServer(
        [httpx2.Response(401, json={"type": "error", "error": {"message": "bad key"}})]
    )

    with pytest.raises(LLMRequestError, match="401"):
        await _anthropic(server).complete_structured(system="s", user="u", schema=AgentReport)

    assert len(server.requests) == 1


async def test_anthropic_connection_errors_are_transient() -> None:
    def boom(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    client = anthropic.AsyncAnthropic(
        api_key="k",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(boom)),
    )
    provider = AnthropicProvider(
        client, model="claude-opus-5-5", effort="high", max_output_tokens=10, max_retries=0
    )

    with pytest.raises(LLMTransientError):
        await provider.complete_structured(system="s", user="u", schema=AgentReport)


# --- OpenAI-compatible -------------------------------------------------------------------

BASE = "http://llm.test/v1/"


def _completion(content: str, *, finish: str = "stop") -> dict[str, Any]:
    return {
        "model": "qwen-coder",
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 900, "completion_tokens": 60},
    }


@pytest.fixture
async def compat() -> AsyncIterator[OpenAICompatProvider]:
    async with httpx.AsyncClient(base_url=BASE) as http:
        yield OpenAICompatProvider(
            http, model="qwen-coder", max_output_tokens=2000, max_retries=2, retry_base_delay=0
        )


@respx.mock
async def test_openai_compat_sends_strict_schema_and_parses(compat: OpenAICompatProvider) -> None:
    route = respx.post(f"{BASE}chat/completions").mock(
        return_value=httpx.Response(200, json=_completion(json.dumps(REPORT)))
    )

    result = await compat.complete_structured(system="sys", user="diff", schema=AgentReport)

    assert result.value.findings[0].path == "app/users.py"
    assert result.usage.input_tokens == 900
    body = json.loads(route.calls.last.request.content)
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"]["additionalProperties"] is False


@respx.mock
@pytest.mark.parametrize(
    ("completion", "message"),
    [
        (_completion("{not json"), "did not match"),
        (_completion(json.dumps(REPORT), finish="length"), "truncated"),
        ({"model": "m", "choices": []}, "no choices"),
    ],
)
async def test_openai_compat_bad_output(
    compat: OpenAICompatProvider, completion: dict[str, Any], message: str
) -> None:
    respx.post(f"{BASE}chat/completions").mock(return_value=httpx.Response(200, json=completion))

    with pytest.raises(LLMOutputError, match=message):
        await compat.complete_structured(system="s", user="u", schema=AgentReport)


@respx.mock
async def test_openai_compat_retries_server_errors(compat: OpenAICompatProvider) -> None:
    route = respx.post(f"{BASE}chat/completions").mock(
        side_effect=[
            httpx.Response(503),
            httpx.ConnectTimeout("slow"),
            httpx.Response(200, json=_completion(json.dumps(REPORT))),
        ]
    )

    result = await compat.complete_structured(system="s", user="u", schema=AgentReport)

    assert len(result.value.findings) == 1
    assert route.call_count == 3


@respx.mock
async def test_openai_compat_client_error_is_not_retried(compat: OpenAICompatProvider) -> None:
    route = respx.post(f"{BASE}chat/completions").mock(
        return_value=httpx.Response(404, text="model not found")
    )

    with pytest.raises(LLMRequestError, match="404"):
        await compat.complete_structured(system="s", user="u", schema=AgentReport)

    assert route.call_count == 1
