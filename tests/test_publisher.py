import json
from typing import Any

import pytest

from reviewcrew.agents.models import AgentResult, Finding
from reviewcrew.diff.processor import ProcessedDiff, process_diff
from reviewcrew.llm.base import TokenUsage
from reviewcrew.pipeline.publisher import (
    MAX_BODY_CHARS,
    ReviewReport,
    build_review,
    format_comment,
)
from reviewcrew.pipeline.verifier import verify
from tests.helpers import load_diff

KEY = "pk9f3Kq7Zr2LmX8vBn4TdW1yHs6Gc0Ea"
SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture(scope="module")
def diff() -> ProcessedDiff:
    return process_diff(load_diff("vulnerable.diff"))


def finding(path: str = "app/users.py", line: int = 11, **overrides: object) -> Finding:
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


def report(
    diff: ProcessedDiff, *findings: Finding, max_inline: int = 20, **extra: Any
) -> ReviewReport:
    results = tuple(
        AgentResult(
            agent=agent,
            findings=tuple(f for f in findings if f.agent == agent and f.source == "llm"),
            usage=TokenUsage(input_tokens=1000, output_tokens=200),
            duration_seconds=2.5,
            errors=extra.pop(f"{agent}_errors", ()),
        )
        for agent in ("security", "performance", "tests")
    )
    return ReviewReport(
        results=results,
        diff=diff,
        verified=verify(findings, diff),
        max_inline_comments=max_inline,
        head_sha=SHA,
        duration_seconds=7.25,
        **extra,
    )


def review(diff: ProcessedDiff, *findings: Finding, **kwargs: Any) -> dict[str, Any]:
    return build_review(report(diff, *findings, **kwargs), secrets={KEY}).to_api()


def test_review_is_always_a_comment_on_the_head_commit(diff: ProcessedDiff) -> None:
    payload = review(diff, finding())

    assert payload["event"] == "COMMENT"
    assert payload["commit_id"] == SHA


def test_verified_findings_become_inline_comments(diff: ProcessedDiff) -> None:
    payload = review(diff, finding(line=11, end_line=12), finding("app/settings.py", 9))

    comments = {(c["path"], c.get("start_line"), c["line"]) for c in payload["comments"]}
    assert comments == {("app/users.py", 11, 12), ("app/settings.py", None, 9)}
    assert all(c["side"] == "RIGHT" for c in payload["comments"])


def test_agent_table_tokens_time_and_status(diff: ProcessedDiff) -> None:
    payload = review(
        diff,
        finding(),
        finding("app/settings.py", 9, severity="critical"),
        finding(agent="performance", line=12, severity="medium", title="fetchall"),
        tests_errors=("chunk 0: crashed (RuntimeError)",),
    )

    body = payload["body"]
    assert "| 🔒 Security | 2 | critical | 1,200 | 2.5s | ✅ |" in body
    assert "| ⚡ Performance | 1 | medium | 1,200 | 2.5s | ✅ |" in body
    assert "| 🧪 Tests | 0 | — | 1,200 | 2.5s | ⚠️ 1 error |" in body
    assert "**3 findings**: 3 inline." in body
    assert "tests: chunk 0: crashed (RuntimeError)" in body
    assert "3,600 tokens · 7.2s total" in body


def test_hidden_counts_are_reported(diff: ProcessedDiff) -> None:
    payload = review(diff, finding(), below_confidence=4, duplicates_merged=2)

    assert "4 low-confidence findings hidden · 2 duplicates merged" in payload["body"]


def test_inline_limit_moves_the_rest_to_the_summary(diff: ProcessedDiff) -> None:
    findings = [
        finding(line=line, severity=sev, title=f"Issue {line}")
        for line, sev in [(11, "critical"), (12, "medium"), (10, "low")]
    ]

    payload = review(diff, *findings, max_inline=2)

    assert [c["line"] for c in payload["comments"]] == [11, 12]
    assert "More findings (inline limit of 2 reached)" in payload["body"]
    assert "`app/users.py:10`" in payload["body"]
    assert "User input reaches the query." in payload["body"]  # explanation not lost


def test_findings_outside_the_diff_go_to_the_summary(diff: ProcessedDiff) -> None:
    payload = review(diff, finding(line=2, title="Pre-existing issue"))

    assert payload["comments"] == []
    assert "### Findings outside the changed lines" in payload["body"]
    assert "`app/users.py:2`" in payload["body"]


def test_summary_only_mode_for_the_422_fallback(diff: ProcessedDiff) -> None:
    payload = build_review(report(diff, finding()), secrets=set(), allow_inline=False).to_api()

    assert payload["comments"] == []
    assert "### Findings\n" in payload["body"]
    assert "inline limit" not in payload["body"]


def test_secrets_never_appear_in_the_review(diff: ProcessedDiff) -> None:
    leaky = finding(
        "app/settings.py",
        9,
        title=f"Hardcoded key {KEY}",
        explanation=f"The value {KEY} is committed.",
        suggestion=f'Replace "{KEY}" with os.environ["PAYMENTS_API_KEY"].',
    )

    payload = review(diff, leaky, finding("app/settings.py", 1, explanation=f"Also {KEY}"))

    assert KEY not in json.dumps(payload)
    assert "pk9f…[REDACTED]" in payload["comments"][0]["body"]


def test_no_reviewable_files() -> None:
    payload = build_review(report(process_diff("")), secrets=set()).to_api()

    assert "No reviewable changes" in payload["body"]


def test_body_is_capped_below_githubs_limit(diff: ProcessedDiff) -> None:
    long = "x" * 5000
    findings = [finding(line=2, title=f"Old issue {i}", explanation=long) for i in range(30)]

    payload = review(diff, *findings)

    assert len(payload["body"]) <= MAX_BODY_CHARS
    assert payload["body"].endswith("(summary truncated)")


def test_comment_format() -> None:
    body = format_comment(finding(agent="tests", severity="medium", confidence=0.875))

    assert body.startswith("**🧪 Tests · Medium** · confidence 0.88")
    assert "**SQL injection**" in body
    assert "**Suggested fix**" in body


def test_rule_findings_have_their_own_row_and_label(diff: ProcessedDiff) -> None:
    secret = finding("app/settings.py", 9, source="rule", title="Hardcoded secret")

    payload = review(diff, finding(), secret, rule_findings=(secret,))

    body = payload["body"]
    assert "| 🔒 Security | 1 | high |" in body  # the LLM agent's own finding only
    assert "| 🔑 Secret scan (rule) | 1 | high | — | — | ✅ |" in body
    comments = {c["line"]: c["body"] for c in payload["comments"]}
    assert comments[9].startswith("**🔑 Secret scan (rule) · High**")
    assert comments[11].startswith("**🔒 Security · High**")


def test_no_rule_row_when_the_scan_did_not_run(diff: ProcessedDiff) -> None:
    assert "Secret scan" not in review(diff, finding())["body"]


def test_raw_counts_and_off_category_drops_are_shown(diff: ProcessedDiff) -> None:
    shown = finding()
    base = report(diff, shown)
    security = base.results[0].model_copy(
        update={"findings": (shown, finding(line=12, title="merged away")), "off_category": 2}
    )
    body = build_review(
        base.model_copy(update={"results": (security, *base.results[1:])}), secrets=set()
    ).body

    assert "| 🔒 Security | 1 (2 raw) | high |" in body
    assert "2 findings outside the reporting agent's area dropped" in body
