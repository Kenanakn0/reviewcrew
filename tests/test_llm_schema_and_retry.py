from typing import Any, Literal

import pytest
from pydantic import BaseModel, Field

from reviewcrew.agents.models import AgentReport
from reviewcrew.llm.base import LLMRequestError, LLMTransientError
from reviewcrew.llm.retry import with_retries
from reviewcrew.llm.schema import strict_json_schema


class Inner(BaseModel):
    pattern: str  # a *field* named like a JSON Schema keyword must survive
    score: float = Field(ge=0, le=1)


class Outer(BaseModel):
    name: str = Field(min_length=1, max_length=10)
    kind: Literal["a", "b"]
    note: str | None = None
    items: list[Inner]


def _objects(node: Any) -> list[dict[str, Any]]:
    found = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            found.append(node)
        for value in node.values():
            found += _objects(value)
    elif isinstance(node, list):
        for value in node:
            found += _objects(value)
    return found


def _keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for value in node.values() for k in _keys(value)}
    if isinstance(node, list):
        return {k for value in node for k in _keys(value)}
    return set()


def test_strict_schema_closes_every_object_and_requires_all_fields() -> None:
    schema = strict_json_schema(Outer)

    objects = _objects(schema)
    assert len(objects) == 2
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])


def test_strict_schema_drops_unsupported_constraints_but_keeps_field_names() -> None:
    schema = strict_json_schema(Outer)

    assert not {"minLength", "maxLength", "minimum", "maximum", "default"} & (
        _keys(schema) - {"pattern"}
    )
    assert "pattern" in schema["$defs"]["Inner"]["properties"]


def test_agent_report_schema_is_strict() -> None:
    schema = strict_json_schema(AgentReport)

    finding = schema["$defs"]["FindingDraft"]
    assert finding["additionalProperties"] is False
    assert "end_line" in finding["required"]  # nullable, but must be present
    assert finding["required"][0] == "category"  # asked first, before the details
    assert finding["properties"]["category"]["enum"] == ["security", "performance", "tests"]


class Flaky:
    def __init__(self, failures: list[Exception]) -> None:
        self.failures = failures
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return "ok"


class RecordingSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


async def test_transient_errors_are_retried_with_growing_delays() -> None:
    operation = Flaky([LLMTransientError("429"), LLMTransientError("503")])
    sleep = RecordingSleep()

    result = await with_retries(operation, max_retries=3, base_delay=1.0, sleep=sleep)

    assert result == "ok"
    assert operation.calls == 3
    assert len(sleep.delays) == 2
    assert 0 <= sleep.delays[0] <= 1.0  # full jitter within base * 2**0
    assert 0 <= sleep.delays[1] <= 2.0  # ... and base * 2**1


async def test_retry_after_is_honoured() -> None:
    operation = Flaky([LLMTransientError("429", retry_after=7.0)])
    sleep = RecordingSleep()

    await with_retries(operation, max_retries=1, base_delay=0.01, sleep=sleep)

    assert sleep.delays == [7.0]


async def test_gives_up_after_max_retries() -> None:
    operation = Flaky([LLMTransientError(f"fail {i}") for i in range(5)])

    with pytest.raises(LLMTransientError, match="fail 2"):
        await with_retries(operation, max_retries=2, sleep=RecordingSleep())

    assert operation.calls == 3


async def test_non_transient_errors_are_not_retried() -> None:
    operation = Flaky([LLMRequestError("bad key")])

    with pytest.raises(LLMRequestError):
        await with_retries(operation, max_retries=5, sleep=RecordingSleep())

    assert operation.calls == 1
