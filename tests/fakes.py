"""In-memory test doubles."""

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from reviewcrew.llm.base import SchemaT, StructuredResponse, TokenUsage

Step = BaseModel | Exception | Callable[[str, str], BaseModel]


@dataclass
class FakeLLM:
    """Replays scripted outputs: a model instance, an exception to raise, or a callable
    `(system, user) -> model` for content-dependent answers. The last step repeats."""

    steps: list[Step]
    usage: TokenUsage = field(
        default_factory=lambda: TokenUsage(input_tokens=100, output_tokens=20)
    )
    calls: list[tuple[str, str]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "fake"

    async def complete_structured(
        self, *, system: str, user: str, schema: type[SchemaT]
    ) -> StructuredResponse[SchemaT]:
        self.calls.append((system, user))
        step = self.steps[min(len(self.calls), len(self.steps)) - 1]
        if isinstance(step, Exception):
            raise step
        value = step if isinstance(step, BaseModel) else step(system, user)
        assert isinstance(value, schema)
        return StructuredResponse(value=value, usage=self.usage, model="fake-model")


ROLE_MARKERS = {
    "security": "security engineer",
    "performance": "performance engineer",
    "tests": "specialises in testing",
}


@dataclass
class RoutingLLM:
    """One shared provider (as in production) that answers per agent, recognised from
    the system prompt. Unlisted agents get an empty report."""

    routes: dict[str, Step]
    usage: TokenUsage = field(
        default_factory=lambda: TokenUsage(input_tokens=100, output_tokens=20)
    )
    calls: list[tuple[str, str]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "routing-fake"

    def agent_of(self, system: str) -> str:
        return next(agent for agent, marker in ROLE_MARKERS.items() if marker in system)

    async def complete_structured(
        self, *, system: str, user: str, schema: type[SchemaT]
    ) -> StructuredResponse[SchemaT]:
        self.calls.append((system, user))
        step = self.routes.get(self.agent_of(system))
        if isinstance(step, Exception):
            raise step
        if step is None:
            value: BaseModel = schema.model_validate({"findings": []})
        else:
            value = step if isinstance(step, BaseModel) else step(system, user)
        assert isinstance(value, schema)
        return StructuredResponse(value=value, usage=self.usage, model="fake-model")
