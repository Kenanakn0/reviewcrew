"""Decide where each finding can be shown: inline on the diff, or in the summary."""

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from reviewcrew.agents.models import Finding
from reviewcrew.diff.processor import ProcessedDiff


class InlineFinding(BaseModel):
    """A finding anchored to lines GitHub accepts for a RIGHT-side review comment."""

    model_config = ConfigDict(frozen=True)

    finding: Finding
    line: int  # last line of the comment
    start_line: int | None = None  # first line, for multi-line comments


class VerifiedFindings(BaseModel):
    model_config = ConfigDict(frozen=True)

    inline: tuple[InlineFinding, ...] = ()
    outside: tuple[Finding, ...] = ()  # real file, but the line is not part of the diff
    unknown_file: int = 0  # dropped: the file is not among the reviewed files


def anchor(finding: Finding, diff: ProcessedDiff) -> InlineFinding | None:
    if not diff.is_commentable(finding.path, finding.line):
        return None
    end = finding.end_line
    if end is not None and diff.is_commentable(finding.path, end):
        file = diff.files[finding.path]
        # Multi-line comments must stay within one hunk.
        if file.hunk_for_line(finding.line) is file.hunk_for_line(end):
            return InlineFinding(finding=finding, line=end, start_line=finding.line)
    return InlineFinding(finding=finding, line=finding.line)


def verify(findings: Iterable[Finding], diff: ProcessedDiff) -> VerifiedFindings:
    """Keep the input order. Findings on unknown files are dropped (hallucinated paths)."""
    inline: list[InlineFinding] = []
    outside: list[Finding] = []
    unknown = 0
    for finding in findings:
        if finding.path not in diff.files:
            unknown += 1
            continue
        anchored = anchor(finding, diff)
        if anchored is None:
            outside.append(finding)
        else:
            inline.append(anchored)
    return VerifiedFindings(inline=tuple(inline), outside=tuple(outside), unknown_file=unknown)
