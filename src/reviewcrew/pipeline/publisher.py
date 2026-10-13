"""Render a finished review run as a single GitHub review: inline comments plus a summary."""

from collections.abc import Iterable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from reviewcrew.agents.models import AgentName, AgentResult, Finding
from reviewcrew.diff.filters import SkipReason
from reviewcrew.diff.processor import ProcessedDiff
from reviewcrew.pipeline.aggregator import rank_key
from reviewcrew.pipeline.verifier import InlineFinding, VerifiedFindings
from reviewcrew.redaction import redact
from reviewcrew.repo_config.schema import CONFIG_PATH, LoadedConfig

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
    "ignored": "ignored by .reviewcrew.yml",
}
MAX_LISTED = 30  # per summary section
# GitHub rejects review bodies over 65,536 characters; stay well below.
MAX_BODY_CHARS = 60_000
TRUNCATED_NOTICE = "\n\n…(summary truncated)"


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


class ReviewReport(BaseModel):
    """Everything the review run produced, ready to be rendered."""

    model_config = ConfigDict(frozen=True)

    results: tuple[AgentResult, ...]
    diff: ProcessedDiff
    verified: VerifiedFindings
    below_confidence: int = 0
    below_severity: int = 0
    duplicates_merged: int = 0
    max_inline_comments: int = 20
    repo_config: LoadedConfig = LoadedConfig()
    token_budget: int | None = None
    head_sha: str
    duration_seconds: float


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


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _finding_list(title: str, findings: Sequence[Finding], *, details: bool) -> list[str]:
    if not findings:
        return []
    lines = ["", f"### {title}", ""]
    for finding in sorted(findings, key=rank_key)[:MAX_LISTED]:
        lines.append(
            f"- **{finding.severity.capitalize()}** {_location(finding)} "
            f"({AGENT_LABELS[finding.agent]}): {finding.title}"
        )
        if details:
            lines.append(f"  {finding.explanation}")
    if len(findings) > MAX_LISTED:
        lines.append(f"- …and {len(findings) - MAX_LISTED} more")
    return lines


def _agent_table(report: ReviewReport, shown: Sequence[Finding]) -> list[str]:
    lines = [
        "| Agent | Findings | Highest severity | Tokens | Time | Status |",
        "|---|---:|---|---:|---:|---|",
    ]
    for result in report.results:
        mine = sorted((f for f in shown if f.agent == result.agent), key=rank_key)
        highest = mine[0].severity if mine else "—"
        problems = []
        if result.errors:
            problems.append(f"⚠️ {_plural(len(result.errors), 'error')}")
        if result.skipped_chunks:
            problems.append(f"⏭️ {result.skipped_chunks} skipped")
        status = ", ".join(problems) or "✅"
        lines.append(
            f"| {AGENT_LABELS[result.agent]} | {len(mine)} | {highest} | "
            f"{result.usage.total_tokens:,} | {result.duration_seconds:.1f}s | {status} |"
        )
    return lines


def build_summary(
    report: ReviewReport,
    *,
    inline: Sequence[InlineFinding],
    overflow: Sequence[Finding],
    inline_disabled: bool = False,
) -> str:
    outside = report.verified.outside
    shown = [item.finding for item in inline] + list(overflow) + list(outside)
    diff = report.diff
    lines = ["## 🛡️ ReviewCrew review", ""]
    if report.repo_config.errors:
        lines += [
            f"⚠️ `{CONFIG_PATH}` is invalid, so the default settings were used:",
            "",
            *(f"- {error}" for error in report.repo_config.errors[:MAX_LISTED]),
            "",
        ]

    if not diff.chunks:
        lines.append("No reviewable changes in this pull request.")
    else:
        lines += _agent_table(report, shown)
        placement = [f"{len(inline)} inline"]
        if overflow or outside:
            placement.append(f"{len(overflow) + len(outside)} listed below")
        lines += ["", f"**{_plural(len(shown), 'finding')}**: {', '.join(placement)}."]
        hidden = []
        if report.below_confidence:
            hidden.append(_plural(report.below_confidence, "low-confidence finding") + " hidden")
        if report.below_severity:
            hidden.append(
                _plural(report.below_severity, "finding")
                + f" below min_severity ({report.repo_config.config.min_severity}) hidden"
            )
        if report.duplicates_merged:
            hidden.append(_plural(report.duplicates_merged, "duplicate") + " merged")
        if report.verified.unknown_file:
            hidden.append(
                _plural(report.verified.unknown_file, "finding") + " on unknown files dropped"
            )
        if hidden:
            lines.append(f"<sub>{' · '.join(hidden)}</sub>")

    overflow_title = (
        "Findings"
        if inline_disabled
        else f"More findings (inline limit of {report.max_inline_comments} reached)"
    )
    lines += _finding_list(overflow_title, overflow, details=True)
    lines += _finding_list("Findings outside the changed lines", outside, details=True)

    skipped_chunks = {r.agent: r.skipped_chunks for r in report.results if r.skipped_chunks}
    if skipped_chunks:
        per_agent = ", ".join(f"{agent}: {count}" for agent, count in skipped_chunks.items())
        budget = f"{report.token_budget:,} tokens" if report.token_budget else "the token budget"
        lines += [
            "",
            f"⏭️ The per-PR budget of {budget} was reached; "
            f"{_plural(sum(skipped_chunks.values()), 'chunk')} not reviewed ({per_agent}).",
        ]

    errors = [f"{result.agent}: {error}" for result in report.results for error in result.errors]
    if errors:
        lines += ["", "⚠️ Some parts could not be reviewed:", ""]
        lines += [f"- {error}" for error in errors[:MAX_LISTED]]

    if diff.skipped:
        lines += ["", f"<details><summary>Skipped files ({len(diff.skipped)})</summary>", ""]
        for skipped in diff.skipped[:MAX_LISTED]:
            path = skipped.path.replace("`", "'")
            lines.append(f"- `{path}` ({SKIP_REASON_LABELS[skipped.reason]})")
        if len(diff.skipped) > MAX_LISTED:
            lines.append(f"- …and {len(diff.skipped) - MAX_LISTED} more")
        lines += ["", "</details>"]

    tokens = sum(result.usage.total_tokens for result in report.results)
    lines += [
        "",
        f"<sub>Reviewed {len(diff.files)} of {diff.total_files} files in "
        f"{_plural(len(diff.chunks), 'chunk')} · {tokens:,} tokens · "
        f"{report.duration_seconds:.1f}s total · commit {report.head_sha[:7]} · "
        + (f"settings from `{CONFIG_PATH}` · " if report.repo_config.source == "file" else "")
        + "automated suggestions, please verify.</sub>",
    ]
    body = "\n".join(lines)
    if len(body) > MAX_BODY_CHARS:
        body = body[: MAX_BODY_CHARS - len(TRUNCATED_NOTICE)] + TRUNCATED_NOTICE
    return body


def build_review(
    report: ReviewReport, *, secrets: Iterable[str], allow_inline: bool = True
) -> ReviewPayload:
    """Inline comments up to the limit; everything else goes to the summary.

    All text passes through secret redaction before it leaves the process.
    """
    secrets = set(secrets)
    candidates = list(report.verified.inline)
    limit = report.max_inline_comments if allow_inline else 0
    inline, overflow = candidates[:limit], [item.finding for item in candidates[limit:]]
    comments = tuple(
        ReviewComment(
            path=item.finding.path,
            line=item.line,
            start_line=item.start_line,
            start_side="RIGHT" if item.start_line is not None else None,
            body=redact(format_comment(item.finding), secrets),
        )
        for item in inline
    )
    summary = build_summary(
        report, inline=inline, overflow=overflow, inline_disabled=not allow_inline
    )
    return ReviewPayload(
        commit_id=report.head_sha, body=redact(summary, secrets), comments=comments
    )
