import pytest

from reviewcrew.agents.models import Finding
from reviewcrew.pipeline.aggregator import (
    AggregationConfig,
    aggregate,
    is_duplicate,
    title_similarity,
)


def finding(**overrides: object) -> Finding:
    fields: dict[str, object] = {
        "agent": "security",
        "path": "app/users.py",
        "line": 11,
        "severity": "high",
        "confidence": 0.9,
        "title": "SQL injection",
        "explanation": "e",
    }
    fields.update(overrides)
    return Finding.model_validate(fields)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("SQL injection", "SQL injection via f-string in find_users_by_name"),
        ("N+1 query in order loop", "Query executed inside loop (N+1)"),
        ("Missing tests for find_users_by_name", "find_users_by_name has no tests"),
        ("Hardcoded API key", "hardcoded api key!"),
    ],
)
def test_similar_titles(a: str, b: str) -> None:
    assert title_similarity(a, b) >= AggregationConfig().title_similarity


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("SQL injection", "Missing tests for find_users_by_name"),
        ("Missing test for empty name", "Missing test for SQL special characters"),
        ("Unbounded fetchall", "SQL injection"),
        ("", "SQL injection"),
    ],
)
def test_different_titles(a: str, b: str) -> None:
    assert title_similarity(a, b) < AggregationConfig().title_similarity


def test_duplicate_needs_same_file_nearby_lines_and_similar_title() -> None:
    config = AggregationConfig(line_proximity=3)
    base = finding(line=11)

    assert is_duplicate(base, finding(line=14, title="SQL injection in search"), config)
    assert not is_duplicate(base, finding(line=15), config)  # too far
    assert not is_duplicate(base, finding(path="app/other.py"), config)
    assert not is_duplicate(base, finding(title="Unbounded fetchall"), config)


def test_overlapping_ranges_count_as_near() -> None:
    config = AggregationConfig(line_proximity=0)

    assert is_duplicate(finding(line=10, end_line=20), finding(line=18), config)


def test_duplicates_across_agents_are_merged_keeping_the_strongest() -> None:
    weaker = finding(agent="performance", severity="medium", confidence=0.95, line=12)
    stronger = finding(agent="security", severity="critical", confidence=0.7, line=11)

    result = aggregate([weaker, stronger])

    (kept,) = result.findings
    assert (kept.agent, kept.severity, kept.line) == ("security", "critical", 11)
    assert kept.confidence == 0.95  # the group's highest confidence
    assert result.duplicates_merged == 1


def test_low_confidence_findings_are_dropped_and_counted() -> None:
    result = aggregate(
        [finding(confidence=0.49), finding(line=40, title="Other", confidence=0.5)],
        AggregationConfig(min_confidence=0.5),
    )

    assert [f.line for f in result.findings] == [40]
    assert result.below_confidence == 1


def test_low_confidence_duplicate_does_not_boost_a_kept_finding() -> None:
    result = aggregate([finding(confidence=0.6), finding(line=12, confidence=0.3)])

    (kept,) = result.findings
    assert kept.confidence == 0.6
    assert (result.below_confidence, result.duplicates_merged) == (1, 0)


def test_results_are_sorted_by_severity_then_confidence() -> None:
    findings = [
        finding(line=1, title="a", severity="low", confidence=0.99),
        finding(line=20, title="b", severity="critical", confidence=0.6),
        finding(line=40, title="c", severity="critical", confidence=0.9),
        finding(line=60, title="d", severity="medium", confidence=0.8),
    ]

    result = aggregate(findings)

    assert [f.title for f in result.findings] == ["c", "b", "d", "a"]


def test_distinct_issues_on_the_same_line_are_kept() -> None:
    sqli = finding(title="SQL injection")
    select_star = finding(agent="performance", title="SELECT * fetches unused columns")

    assert len(aggregate([sqli, select_star]).findings) == 2


def test_empty_input() -> None:
    result = aggregate([])

    assert (result.findings, result.below_confidence, result.duplicates_merged) == ((), 0, 0)
