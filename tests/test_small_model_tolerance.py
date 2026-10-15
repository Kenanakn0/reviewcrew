"""Small local models (e.g. qwen2.5-coder:7b on Ollama) make predictable formatting mistakes.
These tests pin down which ones are tolerated and that the rest still degrade gracefully:
retried once, then reported as an error without stopping the review."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx

from reviewcrew.agents.models import AgentReport
from reviewcrew.agents.security import SecurityAgent
from reviewcrew.diff.processor import process_diff
from reviewcrew.llm.openai_compat import OpenAICompatProvider, extract_json_object
from tests.helpers import load_diff

BASE = "http://ollama.test/v1/"
GOOD = {
    "path": "app/users.py",
    "line": 11,
    "end_line": None,
    "severity": "critical",
    "confidence": 0.9,
    "title": "SQL injection",
    "explanation": "name is interpolated",
    "suggestion": None,
}


def _completion(content: str) -> dict[str, Any]:
    return {
        "model": "qwen2.5-coder:7b",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 800, "completion_tokens": 90},
    }


@pytest.fixture
async def ollama() -> AsyncIterator[OpenAICompatProvider]:
    async with httpx.AsyncClient(base_url=BASE) as http:
        yield OpenAICompatProvider(
            http, model="qwen2.5-coder:7b", max_output_tokens=2000, max_retries=0
        )


# --- tolerated -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        f"```json\n{json.dumps({'findings': [GOOD]})}\n```",
        f"```\n{json.dumps({'findings': [GOOD]})}\n```",
        f"Here is my review:\n{json.dumps({'findings': [GOOD]})}\nLet me know!",
        f"  {json.dumps({'findings': [GOOD]})}  ",
    ],
    ids=["json-fence", "plain-fence", "surrounding-prose", "whitespace"],
)
@respx.mock
async def test_wrapped_json_is_accepted(ollama: OpenAICompatProvider, content: str) -> None:
    respx.post(f"{BASE}chat/completions").mock(
        return_value=httpx.Response(200, json=_completion(content))
    )

    result = await ollama.complete_structured(system="s", user="u", schema=AgentReport)

    assert [f.line for f in result.value.findings] == [11]


def test_severity_casing_and_missing_optional_fields() -> None:
    finding = {k: v for k, v in GOOD.items() if k not in ("end_line", "suggestion")}

    report = AgentReport.model_validate({"findings": [finding | {"severity": " High "}]})

    (draft,) = report.findings
    assert (draft.severity, draft.end_line, draft.suggestion) == ("high", None, None)


def test_one_malformed_finding_does_not_discard_the_others() -> None:
    report = AgentReport.model_validate_json(
        json.dumps(
            {
                "findings": [
                    GOOD,
                    {"path": "app/users.py", "line": "eleven", "severity": "high"},
                    GOOD | {"line": 12, "severity": "urgent"},
                    GOOD | {"line": 12},
                ]
            }
        )
    )

    assert [f.line for f in report.findings] == [11, 12]
    assert report.dropped_findings == 2


def test_numeric_strings_are_coerced() -> None:
    report = AgentReport.model_validate_json(
        json.dumps({"findings": [GOOD | {"line": "11", "confidence": "0.8"}]})
    )

    assert (report.findings[0].line, report.findings[0].confidence) == (11, 0.8)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', '{"a": 1}'),
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ('Sure! {"a": {"b": 2}} done', '{"a": {"b": 2}}'),
        ("no json here", "no json here"),
    ],
)
def test_extract_json_object(text: str, expected: str) -> None:
    assert extract_json_object(text) == expected


# --- not tolerated, but handled ----------------------------------------------------------------


@respx.mock
async def test_garbage_then_valid_output_is_recovered_by_the_retry(
    ollama: OpenAICompatProvider,
) -> None:
    route = respx.post(f"{BASE}chat/completions").mock(
        side_effect=[
            httpx.Response(200, json=_completion('{"findings": [ {"path": "app/us')),
            httpx.Response(200, json=_completion(json.dumps({"findings": [GOOD]}))),
        ]
    )
    chunk = process_diff(load_diff("vulnerable.diff")).chunks[0]

    result = await SecurityAgent(ollama).review_chunk(chunk, pr_title="t", chunk_count=1)

    assert route.call_count == 2
    assert [f.line for f in result.findings] == [11]
    assert result.errors == ()
    assert result.usage.input_tokens == 1600  # the failed attempt is counted too


@respx.mock
async def test_persistent_garbage_becomes_a_reported_error(
    ollama: OpenAICompatProvider,
) -> None:
    respx.post(f"{BASE}chat/completions").mock(
        return_value=httpx.Response(200, json=_completion("I cannot produce JSON, sorry."))
    )
    chunk = process_diff(load_diff("vulnerable.diff")).chunks[0]

    result = await SecurityAgent(ollama).review_chunk(chunk, pr_title="t", chunk_count=1)

    assert result.findings == ()
    assert result.errors == ("chunk 0: the model returned unusable output",)
