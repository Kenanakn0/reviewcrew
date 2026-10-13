import json
from typing import Any

import pytest

from reviewcrew.agents.models import AgentResult, Finding
from reviewcrew.diff.processor import ProcessedDiff, process_diff
from reviewcrew.llm.base import TokenUsage
from reviewcrew.pipeline.publisher import build_review, format_comment, sort_findings
from tests.helpers import load_diff

KEY = "pk9f3Kq7Zr2LmX8vBn4TdW1yHs6Gc0Ea"
SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture(scope="module")
def diff() -> ProcessedDiff:
    return process_diff(load_diff("vulnerable.diff"))


def _finding(path: str = "app/users.py", line: int = 11, **overrides: object) -> Finding:
    fields: dict[str, object] = {
        "agent": "security",
        "path": path,
        "line": line,
        "severity": "high",
        "confidence": 0.9,
        "title": "SQL injection",
        "explanation": "User input reaches the query.",
        "suggestion": "Use placeholders.",
    }
    fields.update(overrides)
    return Finding.model_validate(fields)


def _review(
    diff: ProcessedDiff, *findings: Finding, errors: tuple[str, ...] = ()
) -> dict[str, Any]:
    result = AgentResult(
        agent="security",
        findings=findings,
        usage=TokenUsage(input_tokens=1000, output_tokens=200),
        errors=errors,
    )
    return build_review([result], diff, head_sha=SHA, secrets={KEY}, duration_seconds=3.2).to_api()


def test_review_is_always_a_comment_on_the_head_commit(diff: ProcessedDiff) -> None:
    review = _review(diff, _finding())

    assert review["event"] == "COMMENT"
    assert review["commit_id"] == SHA


def test_findings_on_diff_lines_become_inline_comments(diff: ProcessedDiff) -> None:
    review = _review(diff, _finding("app/users.py", 11), _finding("app/settings.py", 9))

    anchors = {(c["path"], c["line"], c["side"]) for c in review["comments"]}
    assert anchors == {("app/users.py", 11, "RIGHT"), ("app/settings.py", 9, "RIGHT")}
    assert all("start_line" not in c for c in review["comments"])  # None fields are dropped


def test_multi_line_finding_within_a_hunk(diff: ProcessedDiff) -> None:
    review = _review(diff, _finding(line=11, end_line=12))

    (comment,) = review["comments"]
    assert (comment["start_line"], comment["line"], comment["start_side"]) == (11, 12, "RIGHT")


def test_end_line_outside_the_diff_falls_back_to_a_single_line(diff: ProcessedDiff) -> None:
    review = _review(diff, _finding(line=12, end_line=40))

    (comment,) = review["comments"]
    assert comment["line"] == 12
    assert "start_line" not in comment


def test_findings_outside_the_diff_go_to_the_summary(diff: ProcessedDiff) -> None:
    review = _review(diff, _finding(line=2, title="Pre-existing issue"))

    assert review["comments"] == []
    assert "### Findings outside the diff" in review["body"]
    assert "`app/users.py:2`" in review["body"]
    assert "Pre-existing issue" in review["body"]


def test_summary_table_and_footer(diff: ProcessedDiff) -> None:
    review = _review(diff, _finding(), _finding("app/settings.py", 9, severity="critical"))

    body = review["body"]
    assert "| 🔒 Security | 2 | critical |" in body
    assert "**2 findings**: 2 inline." in body
    assert "1,200 tokens" in body
    assert "commit 0123456" in body


def test_summary_reports_agent_errors(diff: ProcessedDiff) -> None:
    review = _review(diff, errors=("chunk 0: HTTP 529",))

    assert "Some parts could not be reviewed" in review["body"]
    assert "chunk 0: HTTP 529" in review["body"]


def test_secrets_never_appear_in_the_review(diff: ProcessedDiff) -> None:
    leaky = _finding(
        "app/settings.py",
        9,
        title=f"Hardcoded key {KEY}",
        explanation=f"The value {KEY} is committed.",
        suggestion=f'Replace "{KEY}" with os.environ["PAYMENTS_API_KEY"].',
    )
    outside = _finding("app/settings.py", 1, explanation=f"Also seen: {KEY}")

    review = _review(diff, leaky, outside)

    assert KEY not in json.dumps(review)
    assert "pk9f…[REDACTED]" in review["comments"][0]["body"]


def test_inline_can_be_disabled(diff: ProcessedDiff) -> None:
    result = AgentResult(agent="security", findings=(_finding(),))

    review = build_review(
        [result], diff, head_sha=SHA, secrets=set(), duration_seconds=1, allow_inline=False
    ).to_api()

    assert review["comments"] == []
    assert "`app/users.py:11`" in review["body"]


def test_no_reviewable_files() -> None:
    empty = process_diff("")

    review = build_review(
        [AgentResult(agent="security")], empty, head_sha=SHA, secrets=set(), duration_seconds=0
    ).to_api()

    assert "No reviewable changes" in review["body"]


def test_sorting_by_severity_then_confidence() -> None:
    findings = [
        _finding(severity="low", confidence=0.99),
        _finding(severity="critical", confidence=0.5),
        _finding(severity="critical", confidence=0.9),
    ]

    ordered = sort_findings(findings)

    assert [(f.severity, f.confidence) for f in ordered] == [
        ("critical", 0.9),
        ("critical", 0.5),
        ("low", 0.99),
    ]


def test_comment_format() -> None:
    body = format_comment(_finding(confidence=0.875))

    assert body.startswith("**🔒 Security · High** · confidence 0.88")
    assert "**SQL injection**" in body
    assert "**Suggested fix**" in body
