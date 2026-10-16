"""Shared agent behaviour: prompt assembly, the LLM call, retry-once and normalisation."""

import logging
import secrets
from collections.abc import Sequence
from functools import cache
from importlib.resources import files
from typing import ClassVar

from reviewcrew.agents.models import AgentName, AgentReport, AgentResult, Finding, FindingDraft
from reviewcrew.diff.chunker import DiffChunk
from reviewcrew.diff.definitions import CoverageHints
from reviewcrew.llm.base import (
    LLMError,
    LLMOutputError,
    LLMProvider,
    LLMRequestError,
    LLMTransientError,
    TokenUsage,
)

logger = logging.getLogger(__name__)

LANGUAGES = {"en": "English", "tr": "Turkish"}
# One retry after malformed output; transient API errors are retried inside the provider.
MAX_OUTPUT_ATTEMPTS = 2


@cache
def load_prompt(name: str) -> str:
    return (files("reviewcrew.agents") / "prompts" / f"{name}.md").read_text(encoding="utf-8")


def _fill(template: str, **values: str) -> str:
    # Plain replacement: prompts contain code samples whose braces must not be interpreted.
    for key, value in values.items():
        template = template.replace("{" + key + "}", value)
    return template


def public_reason(exc: LLMError) -> str:
    """Short, fixed wording for the PR summary. Details (provider messages, raw model
    output) can reveal infrastructure or echo PR content, so they only go to the logs."""
    if isinstance(exc, LLMOutputError):
        return "the model returned unusable output"
    if isinstance(exc, LLMTransientError):
        return "the LLM provider was unavailable (retries exhausted)"
    if isinstance(exc, LLMRequestError):
        return "the LLM provider rejected the request (check configuration)"
    return "LLM error"


class BaseAgent:
    """A reviewer specialised through its prompt file. Subclasses set the class attributes."""

    name: ClassVar[AgentName]
    role: ClassVar[str]  # e.g. "a senior application security engineer"
    focus: ClassVar[str]  # one-line area of expertise, used in the common prompt
    # Drop findings whose `category` is another agent's area. Small models tend to repeat
    # the most obvious problem (often a security one) whatever reviewer they play.
    enforce_category: ClassVar[bool] = False

    def __init__(self, llm: LLMProvider, *, language: str = "en") -> None:
        self._llm = llm
        self._language = LANGUAGES.get(language, LANGUAGES["en"])

    @property
    def system_prompt(self) -> str:
        common = _fill(
            load_prompt("common"), role=self.role, focus=self.focus, language=self._language
        )
        return f"{common}\n{load_prompt(self.name)}"

    def notes(self, chunk: DiffChunk, *, coverage: CoverageHints | None) -> str:
        """Facts ReviewCrew computed from the diff for this agent; empty by default."""
        return ""

    def user_prompt(
        self,
        chunk: DiffChunk,
        *,
        pr_title: str,
        chunk_count: int,
        deleted_files: Sequence[str] = (),
        coverage: CoverageHints | None = None,
    ) -> str:
        marker = secrets.token_hex(8)
        # Deleted files are filtered out of the diff, but their names matter: removing a
        # test file or a security module is itself worth reviewing.
        deleted = (
            f"Files deleted by this PR (contents not shown): {', '.join(deleted_files)}\n"
            if deleted_files
            else ""
        )
        notes = self.notes(chunk, coverage=coverage)
        return (
            f"Review part {chunk.index + 1} of {chunk_count} of this pull request.\n"
            f"Data identifier: {marker}\n\n"
            f"<<<UNTRUSTED_PR_DATA {marker}>>>\n"
            f"PR title: {pr_title}\n"
            f"{deleted}\n"
            f"{chunk.text}\n"
            f"<<<END_UNTRUSTED_PR_DATA {marker}>>>" + (f"\n\n{notes}" if notes else "")
        )

    async def review_chunk(
        self,
        chunk: DiffChunk,
        *,
        pr_title: str,
        chunk_count: int,
        deleted_files: Sequence[str] = (),
        coverage: CoverageHints | None = None,
    ) -> AgentResult:
        """Review one chunk. Never raises: failures become an empty result with an error."""
        system = self.system_prompt
        user = self.user_prompt(
            chunk,
            pr_title=pr_title,
            chunk_count=chunk_count,
            deleted_files=deleted_files,
            coverage=coverage,
        )
        usage = TokenUsage()
        last_error = ""
        for attempt in range(1, MAX_OUTPUT_ATTEMPTS + 1):
            try:
                response = await self._llm.complete_structured(
                    system=system, user=user, schema=AgentReport
                )
            except LLMOutputError as exc:
                usage += exc.usage
                logger.warning(
                    "%s agent: invalid output for chunk %d (attempt %d/%d): %s",
                    self.name,
                    chunk.index,
                    attempt,
                    MAX_OUTPUT_ATTEMPTS,
                    exc,
                )
                last_error = f"chunk {chunk.index}: {public_reason(exc)}"
                continue
            except LLMError as exc:
                logger.error("%s agent: LLM failed for chunk %d: %s", self.name, chunk.index, exc)
                return AgentResult(
                    agent=self.name,
                    usage=usage,
                    errors=(f"chunk {chunk.index}: {public_reason(exc)}",),
                )
            usage += response.usage
            if response.value.dropped_findings:
                logger.warning(
                    "%s agent: dropped %d malformed finding(s) in chunk %d",
                    self.name,
                    response.value.dropped_findings,
                    chunk.index,
                )
            findings: list[Finding] = []
            off_category = 0
            for draft in response.value.findings:
                finding = self._normalise(draft, chunk)
                if finding is None:
                    continue
                if self.enforce_category and draft.category != self.name:
                    off_category += 1
                    logger.info(
                        "%s agent: dropped off-category (%s) finding %s",
                        self.name,
                        draft.category,
                        finding.log_label(),
                    )
                    continue
                findings.append(finding)
            logger.info(
                "%s agent: chunk %d raw findings: %s",
                self.name,
                chunk.index,
                "; ".join(f.log_label() for f in findings) or "none",
            )
            return AgentResult(
                agent=self.name, findings=tuple(findings), usage=usage, off_category=off_category
            )
        return AgentResult(agent=self.name, usage=usage, errors=(last_error,))

    def _normalise(self, draft: FindingDraft, chunk: DiffChunk) -> Finding | None:
        if draft.path not in chunk.paths:
            logger.warning(
                "%s agent: dropping finding for a file not in chunk %d", self.name, chunk.index
            )
            return None
        end_line = draft.end_line if draft.end_line and draft.end_line > draft.line else None
        return Finding(
            agent=self.name,
            path=draft.path,
            line=draft.line,
            end_line=end_line,
            severity=draft.severity,
            confidence=min(max(draft.confidence, 0.0), 1.0),
            title=draft.title.strip().splitlines()[0] if draft.title.strip() else "Untitled",
            explanation=draft.explanation.strip(),
            suggestion=(draft.suggestion or "").strip() or None,
        )
