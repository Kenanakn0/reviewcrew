"""Turn agent results into a single GitHub review: inline comments plus a summary."""

from collections.abc import Iterable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from reviewcrew.agents.models import SEVERITY_ORDER, AgentName, AgentResult, Finding
from reviewcrew.diff.filters import SkipReason
from reviewcrew.diff.processor import ProcessedDiff
from reviewcrew.redaction import redact

AGENT_LABELS: dict[AgentName, str] = {
    "security": "🔒 Security",
    "performance": "⚡ Performance",
    "tests": "🧪 Tests",
}
SKIP_REASON_LABELS: dict[SkipReason, str] = {
    "removed": "deleted",
    "binary": "binary",
    "submodule": "submodule",
    "symlink": "symlink",
    "no_changes": "no content changes",
    "lock_file": "lock file",
    "minified": "minified",
    "generated": "generated",
    "too_large": "too large",
}
MAX_SKIPPED_LISTED = 20


class ReviewComment(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    line: int
    side: Literal["RIGHT"] = "RIGHT"
    start_line: int | None = None
    start_side: Literal["RIGHT"] | None = None
    body: str


class ReviewPayload(BaseModel):
    """Body of `POST /repos/{repo}/pulls/{n}/reviews`.

    `event` is pinned to COMMENT: the bot never approves or requests changes.
    """

    model_config = ConfigDict(frozen=True)

    commit_id: str
    body: str
    event: Literal["COMMENT"] = "COMMENT"
    comments: tuple[ReviewComment, ...] = ()

    def to_api(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


def sort_findings(findings: Iterable[Finding]) -> list[Finding]:
    return sorted(
        findings, key=lambda f: (SEVERITY_ORDER[f.severity], -f.confidence, f.path, f.line)
    )


def _anchor(finding: Finding, diff: ProcessedDiff) -> tuple[int, int | None] | None:
    """(line, start_line) for an inline comment, or None if GitHub would reject the line."""
    if not diff.is_commentable(finding.path, finding.line):
        return None
    end = finding.end_line
    if end is not None and diff.is_commentable(finding.path, end):
        file = diff.files[finding.path]
        if file.hunk_for_line(finding.line) is file.hunk_for_line(end):
            return end, finding.line  # multi-line comments must stay within one hunk
    return finding.line, None


def format_comment(finding: Finding) -> str:
    lines = [
        f"**{AGENT_LABELS[finding.agent]} · {finding.severity.capitalize()}** "
        f"· confidence {finding.confidence:.2f}",
        "",
        f"**{finding.title}**",
        "",
        finding.explanation,
    ]
    if finding.suggestion:
        lines += ["", "**Suggested fix**", "", finding.suggestion]
    return "\n".join(lines)


def _location(finding: Finding) -> str:
    span = f"{finding.line}-{finding.end_line}" if finding.end_line else str(finding.line)
    return f"`{finding.path.replace('`', "'")}:{span}`"


def _highest(findings: Sequence[Finding]) -> str:
    return sort_findings(findings)[0].severity if findings else "—"


def build_summary(
    results: Sequence[AgentResult],
    diff: ProcessedDiff,
    *,
    inline_count: int,
    outside: Sequence[Finding],
    head_sha: str,
    duration_seconds: float,
) -> str:
    total = sum(len(r.findings) for r in results)
    tokens = sum(r.usage.total_tokens for r in results)
    lines = ["## 🛡️ ReviewCrew review", ""]

    if not diff.chunks:
        lines.append("No reviewable changes in this pull request.")
    else:
        lines += [
            "| Agent | Findings | Highest severity |",
            "|---|---:|---|",
            *(
                f"| {AGENT_LABELS[r.agent]} | {len(r.findings)} | {_highest(r.findings)} |"
                for r in results
            ),
            "",
            f"**{total} finding{'s' if total != 1 else ''}**: {inline_count} inline"
            + (f", {len(outside)} below (not on a changed line)" if outside else "")
            + ".",
        ]

    if outside:
        lines += ["", "### Findings outside the diff", ""]
        for finding in sort_findings(outside):
            lines.append(
                f"- **{finding.severity.capitalize()}** {_location(finding)} "
                f"({AGENT_LABELS[finding.agent]}): {finding.title}"
            )
            lines.append(f"  {finding.explanation}")

    errors = [error for r in results for error in r.errors]
    if errors:
        lines += ["", "⚠️ Some parts could not be reviewed:", ""]
        lines += [f"- {error}" for error in errors]

    if diff.skipped:
        lines += ["", f"<details><summary>Skipped files ({len(diff.skipped)})</summary>", ""]
        for skipped in diff.skipped[:MAX_SKIPPED_LISTED]:
            path = skipped.path.replace("`", "'")
            lines.append(f"- `{path}` ({SKIP_REASON_LABELS[skipped.reason]})")
        if len(diff.skipped) > MAX_SKIPPED_LISTED:
            lines.append(f"- …and {len(diff.skipped) - MAX_SKIPPED_LISTED} more")
        lines += ["", "</details>"]

    lines += [
        "",
        f"<sub>Reviewed {len(diff.files)} of {diff.total_files} files in "
        f"{len(diff.chunks)} chunk{'s' if len(diff.chunks) != 1 else ''} · "
        f"{tokens:,} tokens · {duration_seconds:.1f}s · commit {head_sha[:7]} · "
        "automated suggestions, please verify.</sub>",
    ]
    return "\n".join(lines)


def build_review(
    results: Sequence[AgentResult],
    diff: ProcessedDiff,
    *,
    head_sha: str,
    secrets: Iterable[str],
    duration_seconds: float,
    allow_inline: bool = True,
) -> ReviewPayload:
    """Inline comments for findings on commentable lines; everything else in the summary.

    All text is passed through secret redaction before it leaves the process.
    """
    secrets = set(secrets)
    comments: list[ReviewComment] = []
    outside: list[Finding] = []
    for finding in sort_findings(f for r in results for f in r.findings):
        anchor = _anchor(finding, diff) if allow_inline else None
        if anchor is None:
            outside.append(finding)
            continue
        line, start_line = anchor
        comments.append(
            ReviewComment(
                path=finding.path,
                line=line,
                start_line=start_line,
                start_side="RIGHT" if start_line is not None else None,
                body=redact(format_comment(finding), secrets),
            )
        )
    summary = build_summary(
        results,
        diff,
        inline_count=len(comments),
        outside=outside,
        head_sha=head_sha,
        duration_seconds=duration_seconds,
    )
    return ReviewPayload(
        commit_id=head_sha, body=redact(summary, secrets), comments=tuple(comments)
    )
