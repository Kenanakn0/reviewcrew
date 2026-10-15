"""Typed findings produced by the review agents."""

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

from reviewcrew.llm.base import TokenUsage

AgentName = Literal["security", "performance", "tests"]
Severity = Literal["critical", "high", "medium", "low"]

SEVERITY_ORDER: dict[Severity, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class FindingDraft(BaseModel):
    """What the LLM is asked to return for each issue (validated, then normalised).

    Lenient where small models commonly slip: severity casing and omitted optional fields.
    """

    path: str = Field(description="File path exactly as shown in the FILE header.")
    line: int = Field(description="New-file line number from the left column of the diff.")
    end_line: int | None = Field(
        default=None, description="Last line of a multi-line issue, or null for a single line."
    )
    severity: Severity
    confidence: float = Field(description="0.0-1.0: how sure you are this is a real problem.")
    title: str = Field(description="One-line summary.")
    explanation: str = Field(description="Why this is a problem and its concrete impact.")
    suggestion: str | None = Field(
        default=None, description="How to fix it, ideally with code; or null."
    )

    @field_validator("severity", mode="before")
    @classmethod
    def _lowercase_severity(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class AgentReport(BaseModel):
    """Top-level structured output of every agent call.

    One malformed finding does not discard the rest: invalid items are dropped and
    counted in `dropped_findings`, which is not part of the schema sent to the model.
    """

    findings: list[FindingDraft]
    dropped_findings: SkipJsonSchema[int] = 0

    @model_validator(mode="before")
    @classmethod
    def _drop_invalid_findings(cls, data: object) -> object:
        if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
            return data
        valid = []
        for item in data["findings"]:
            try:
                valid.append(FindingDraft.model_validate(item))
            except ValidationError:
                continue
        return {**data, "findings": valid, "dropped_findings": len(data["findings"]) - len(valid)}


class Finding(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent: AgentName
    path: str
    line: int  # new-file line number (RIGHT side)
    end_line: int | None = None
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    title: str
    explanation: str
    suggestion: str | None = None


class AgentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent: AgentName
    findings: tuple[Finding, ...] = ()
    usage: TokenUsage = TokenUsage()
    errors: tuple[str, ...] = ()  # chunks that produced no usable output, with the reason
    duration_seconds: float = 0.0  # wall-clock time of the whole agent, set by the orchestrator
    skipped_chunks: int = 0  # not reviewed because the PR's token budget ran out

    def __add__(self, other: "AgentResult") -> "AgentResult":
        return AgentResult(
            agent=self.agent,
            findings=self.findings + other.findings,
            usage=self.usage + other.usage,
            errors=self.errors + other.errors,
            duration_seconds=max(self.duration_seconds, other.duration_seconds),
            skipped_chunks=self.skipped_chunks + other.skipped_chunks,
        )
