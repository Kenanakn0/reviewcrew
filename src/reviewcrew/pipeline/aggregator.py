"""Merge the agents' findings: drop low-confidence ones, collapse duplicates, rank the rest."""

import logging
import re
from collections.abc import Iterable
from difflib import SequenceMatcher

from pydantic import BaseModel, ConfigDict, Field

from reviewcrew.agents.models import SEVERITY_ORDER, Finding, Severity

logger = logging.getLogger(__name__)

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "the",
        "this",
        "to",
        "via",
        "with",
    ]
)
_WORD = re.compile(r"[a-z0-9]+")


class AggregationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    min_severity: Severity = "low"
    # Findings on the same file whose line ranges are at most this far apart may be duplicates.
    line_proximity: int = Field(default=3, ge=0)
    # Title similarity (0-1) above which two nearby findings are considered the same issue.
    title_similarity: float = Field(default=0.6, ge=0.0, le=1.0)
    # Looser threshold between a rule finding and an LLM finding of the same agent: the rule
    # pins a known issue to its line, so "Hardcoded database password" next to the secret
    # scan's "Hardcoded secret" is the same problem, not a second one.
    cross_source_similarity: float = Field(default=0.3, ge=0.0, le=1.0)


class AggregationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    findings: tuple[Finding, ...]  # deduplicated, most severe first
    below_confidence: int  # dropped for low confidence
    below_severity: int = 0  # dropped by the repository's min_severity
    duplicates_merged: int


def rank_key(finding: Finding) -> tuple[int, float, str, int]:
    return SEVERITY_ORDER[finding.severity], -finding.confidence, finding.path, finding.line


def _singular(word: str) -> str:
    """Crude plural folding ("tests" ~ "test", "queries" ~ "query"); enough for titles."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _words(title: str) -> set[str]:
    return {_singular(w) for w in _WORD.findall(title.lower()) if w not in _STOPWORDS}


def title_similarity(a: str, b: str) -> float:
    """Best of three views, so "SQL injection" ~ "SQL injection via f-string in search"."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    overlap = len(wa & wb)
    jaccard = overlap / len(wa | wb)
    # Containment only counts when the shorter title has some substance.
    containment = overlap / min(len(wa), len(wb)) if min(len(wa), len(wb)) >= 2 else 0.0
    sequence = SequenceMatcher(None, " ".join(sorted(wa)), " ".join(sorted(wb))).ratio()
    return max(jaccard, 0.8 * containment, sequence * 0.9)


def _span(finding: Finding) -> tuple[int, int]:
    return finding.line, finding.end_line or finding.line


def _near(a: Finding, b: Finding, proximity: int) -> bool:
    (a_start, a_end), (b_start, b_end) = _span(a), _span(b)
    gap = max(a_start, b_start) - min(a_end, b_end)  # negative when the ranges overlap
    return gap <= proximity


def is_duplicate(a: Finding, b: Finding, config: AggregationConfig) -> bool:
    if a.path != b.path or not _near(a, b, config.line_proximity):
        return False
    threshold = (
        config.cross_source_similarity
        if a.source != b.source and a.agent == b.agent
        else config.title_similarity
    )
    return title_similarity(a.title, b.title) >= threshold


def aggregate(
    findings: Iterable[Finding], config: AggregationConfig | None = None
) -> AggregationResult:
    """Filter by confidence, merge duplicates (also across agents) and sort by severity.

    Candidates are visited best-first, so the finding that survives a merge is always the
    most severe and most confident of its group; it inherits the group's highest confidence.
    """
    config = config or AggregationConfig()
    all_findings = list(findings)
    confident = [f for f in all_findings if f.confidence >= config.min_confidence]
    severity_cutoff = SEVERITY_ORDER[config.min_severity]
    severe_enough = [f for f in confident if SEVERITY_ORDER[f.severity] <= severity_cutoff]

    kept: list[Finding] = []
    merged = 0
    for candidate in sorted(severe_enough, key=rank_key):
        for index, existing in enumerate(kept):
            if is_duplicate(existing, candidate, config):
                logger.info(
                    "Merged duplicate %s into %s", candidate.log_label(), existing.log_label()
                )
                if candidate.confidence > existing.confidence:
                    kept[index] = existing.model_copy(update={"confidence": candidate.confidence})
                merged += 1
                break
        else:
            kept.append(candidate)

    return AggregationResult(
        findings=tuple(sorted(kept, key=rank_key)),
        below_confidence=len(all_findings) - len(confident),
        below_severity=len(confident) - len(severe_enough),
        duplicates_merged=merged,
    )
