"""The evaluation harness itself: cases, diff building, scoring, report and runner."""

from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from eval import run as run_module
from eval.cases import (
    HOLDOUT_DIR,
    CaseError,
    EvalCase,
    ExpectedFinding,
    build_diff,
    load_case,
    load_cases,
)
from eval.report import (
    README_END,
    README_START,
    CaseResult,
    RunInfo,
    embed_in_readme,
    full_repeated_report,
    full_report,
    repeated_summary,
    summary_table,
)
from eval.scoring import Counts, score_case
from reviewcrew.agents.models import AgentReport, Finding, FindingDraft
from reviewcrew.config import CoreSettings
from reviewcrew.diff.parser import parse_diff
from reviewcrew.diff.processor import process_diff
from reviewcrew.llm.base import LLMProvider, TokenUsage
from reviewcrew.pipeline.options import ReviewOptions
from tests.fakes import RoutingLLM

CASES = load_cases()
HOLDOUT = load_cases(HOLDOUT_DIR)
BY_TITLE = {case.title: case for case in CASES}

# --- the case set ----------------------------------------------------------------------------


def test_there_are_enough_cases_including_clean_ones() -> None:
    assert len(CASES) >= 20
    assert sum(case.is_clean for case in CASES) >= 5
    assert {e.category for case in CASES for e in case.expected} == {
        "security",
        "performance",
        "tests",
    }
    assert len({case.title for case in CASES}) == len(CASES)  # titles identify cases below


def test_the_holdout_set_covers_every_agent_and_clean_code() -> None:
    per_category = Counter(e.category for case in HOLDOUT for e in case.expected)

    assert 6 <= len(HOLDOUT) <= 8
    assert all(per_category[agent] >= 2 for agent in ("security", "performance", "tests"))
    assert sum(case.is_clean for case in HOLDOUT) >= 2
    assert not {c.name for c in HOLDOUT} & {c.name for c in CASES}
    assert not {c.title for c in HOLDOUT} & set(BY_TITLE)


@pytest.mark.parametrize("case", CASES + HOLDOUT, ids=lambda case: case.name)
def test_every_expected_finding_is_on_a_reviewable_diff_line(case: EvalCase) -> None:
    diff = process_diff(case.diff, new_contents=case.head_contents)

    for expected in case.expected:
        lines = range(expected.start, expected.end + 1)
        assert any(diff.is_commentable(expected.path, n) for n in lines), expected


def test_build_diff_handles_new_modified_and_deleted_files() -> None:
    before = {"keep.py": "a\nb\nc\n", "gone.py": "x\n"}
    after = {"keep.py": "a\nB\nc\n", "new.py": "1\n2\n"}

    files = {f.path: f for f in parse_diff(build_diff(before, after))}

    assert {path: f.status for path, f in files.items()} == {
        "gone.py": "removed",
        "keep.py": "modified",
        "new.py": "added",
    }
    assert files["keep.py"].added_lines == {2}
    assert files["new.py"].added_lines == {1, 2}


def test_build_diff_marks_a_missing_final_newline() -> None:
    (file,) = parse_diff(build_diff({"a.txt": "x\n"}, {"a.txt": "x\ny"}))

    assert [line.content for line in file.hunks[0].lines if line.kind == "added"] == ["y"]


def _write_case(root: Path, yml: str, after: str = "print('hi')\n") -> Path:
    (root / "after").mkdir(parents=True)
    (root / "after" / "app.py").write_text(after, encoding="utf-8")
    (root / "case.yml").write_text(yml, encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("yml", "message"),
    [
        (
            "title: t\nexpected:\n  - {category: security, path: app.py, line_contains: nope}\n",
            "no line in app.py",
        ),
        (
            "title: t\nexpected:\n  - {category: security, path: x.py, line_contains: p}\n",
            "not in after/",
        ),
        (
            "title: t\nscored: [security]\nexpected:\n"
            "  - {category: tests, path: app.py, line_contains: p}\n",
            "not scored",
        ),
        ("title: t\nscored: [security]\nexpected: []\n", "clean cases are scored"),
    ],
)
def test_invalid_cases_are_rejected(tmp_path: Path, yml: str, message: str) -> None:
    with pytest.raises(CaseError, match=message):
        load_case(_write_case(tmp_path / "case", yml))


# --- scoring ---------------------------------------------------------------------------------


def _finding(agent: str = "security", path: str = "app.py", line: int = 10) -> Finding:
    return Finding.model_validate(
        {
            "agent": agent,
            "path": path,
            "line": line,
            "severity": "high",
            "confidence": 0.9,
            "title": "t",
            "explanation": "e",
        }
    )


EXPECTED = ExpectedFinding(category="security", path="app.py", start=10, end=11)


@pytest.mark.parametrize("line", [8, 10, 11, 13])
def test_prediction_within_tolerance_is_a_hit(line: int) -> None:
    counts = score_case([_finding(line=line)], [EXPECTED])

    assert counts["security"] == Counts(tp=1)


@pytest.mark.parametrize(
    "prediction",
    [
        _finding(line=14),  # too far
        _finding(path="other.py"),  # wrong file
        _finding(agent="performance"),  # wrong category
    ],
)
def test_misses(prediction: Finding) -> None:
    counts = score_case([prediction], [EXPECTED])

    assert counts["security"].fn == 1
    assert counts["security"].tp == 0


def test_each_expected_finding_matches_once() -> None:
    counts = score_case([_finding(line=10), _finding(line=11)], [EXPECTED])

    assert counts["security"] == Counts(tp=1, fp=1)


def test_unscored_categories_are_ignored() -> None:
    counts = score_case([_finding(agent="tests")], [EXPECTED], scored=("security",))

    assert set(counts) == {"security"}


def test_metrics() -> None:
    counts = Counts(tp=3, fp=1, fn=2)

    assert counts.precision == 0.75
    assert counts.recall == 0.6
    assert counts.f1 == pytest.approx(2 * 0.75 * 0.6 / 1.35)
    assert Counts().precision is None
    assert Counts(fp=2).f1 is None  # nothing expected: recall undefined
    assert Counts(fn=2, fp=1).f1 == 0.0


# --- runner ----------------------------------------------------------------------------------


def oracle(system: str, user: str) -> AgentReport:
    """Answers exactly what the case expects for the asking agent."""
    agent = RoutingLLM({}).agent_of(system)
    title = next(line for line in user.splitlines() if line.startswith("PR title: "))
    case = BY_TITLE[title.removeprefix("PR title: ")]
    return AgentReport(
        findings=[
            FindingDraft(
                category=agent,
                path=e.path,
                line=e.start,
                end_line=e.end if e.end > e.start else None,
                severity="high",
                confidence=0.9,
                title=e.note or "issue",
                explanation="e",
                suggestion=None,
            )
            for e in case.expected
            if e.category == agent
        ]
    )


def noisy(system: str, user: str) -> AgentReport:
    """Reports a bogus issue on the first added line of every file it sees."""
    agent = RoutingLLM({}).agent_of(system)
    findings = []
    path = None
    for line in user.splitlines():
        if line.startswith("=== FILE: "):
            path = line.removeprefix("=== FILE: ").split(" (")[0]
        elif path and " + " in line and line.split(" + ")[0].strip().isdigit():
            findings.append(
                FindingDraft(
                    category=agent,
                    path=path,
                    line=int(line.split(" + ")[0]),
                    end_line=None,
                    severity="low",
                    confidence=0.9,
                    title="Nitpick",
                    explanation="e",
                    suggestion=None,
                )
            )
            path = None
    return AgentReport(findings=findings)


async def _evaluate(llm: LLMProvider) -> list[CaseResult]:
    return await run_module.evaluate(CASES, llm, ReviewOptions(), model="claude-opus-5-5")


def _overall(results: list[CaseResult]) -> Counts:
    return sum((c for r in results for c in r.counts.values()), Counts())


async def test_a_perfect_reviewer_scores_100_percent() -> None:
    llm = RoutingLLM(dict.fromkeys(("security", "performance", "tests"), oracle))

    results = await _evaluate(llm)

    overall = _overall(results)
    assert (overall.precision, overall.recall) == (1.0, 1.0)
    assert overall.tp == sum(len(case.expected) for case in CASES)
    assert all(r.cost_usd is not None and r.cost_usd > 0 for r in results)


async def test_a_silent_reviewer_finds_nothing() -> None:
    results = await _evaluate(RoutingLLM({}))

    overall = _overall(results)
    assert overall.tp == overall.fp == 0
    assert overall.recall == 0.0


async def test_noise_shows_up_as_false_positives_on_clean_cases() -> None:
    results = await _evaluate(RoutingLLM({"security": noisy}))

    clean = [r for r in results if r.clean]
    assert all(r.counts["security"].fp >= 1 for r in clean)


async def test_main_writes_the_report_and_updates_the_readme(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    @asynccontextmanager
    async def fake_provider(settings: Any) -> AsyncIterator[LLMProvider]:
        yield RoutingLLM(dict.fromkeys(("security", "performance", "tests"), oracle))

    readme = tmp_path / "README.md"
    readme.write_text(f"# X\n\n{README_START}\nold\n{README_END}\n\nrest\n", encoding="utf-8")
    monkeypatch.setattr(run_module, "open_llm_provider", fake_provider)
    monkeypatch.setattr(run_module, "README", readme)
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-5-5")
    output = tmp_path / "results.md"

    code = await run_module.main(
        [
            "--case",
            CASES[0].name,
            "--case",
            CASES[-1].name,
            "--output",
            str(output),
            "--update-readme",
        ]
    )

    assert code == 0
    report = output.read_text(encoding="utf-8")
    assert "# ReviewCrew evaluation results" in report
    assert "Model `claude-sonnet-5-5`" in report
    assert f"| {CASES[0].name} |" in report
    updated = readme.read_text(encoding="utf-8")
    assert "old" not in updated
    assert "| **all LLM agents** |" in updated
    assert "| secret scan (rule) |" in updated
    assert updated.endswith("rest\n")


async def test_unknown_case_selection_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    assert await run_module.main(["--case", "does-not-exist"]) == 2


# --- report ----------------------------------------------------------------------------------


def _result(name: str, clean: bool, counts: Counts, cost: float | None = 0.01) -> CaseResult:
    return CaseResult(
        name=name,
        clean=clean,
        counts={"security": counts},
        usage=TokenUsage(input_tokens=1000, output_tokens=100),
        cost_usd=cost,
        duration_seconds=2.0,
    )


def test_summary_table() -> None:
    info = RunInfo(model="m", settings="effort high", date="2026-10-13")
    results = [
        _result("a", False, Counts(tp=1, fn=1)),
        _result("b", True, Counts(fp=1), cost=0.03),
    ]

    table = summary_table(results, info)

    assert "Model `m` (effort high) · 2 cases, 1 of them clean · 2026-10-13" in table
    assert "| security | 2 | 2 | 1 | 1 | 1 | 50% | 50% | 50% |" in table
    assert "| Cost (list price) | $0.0200 |" in table
    assert "False positives on the 1 clean cases: 1 from the LLM agents, 0 from" in table


def test_full_report_lists_every_case() -> None:
    info = RunInfo(model="m", settings="s", date="d")
    report = full_report([_result("case_one", True, Counts(), cost=None)], info)

    assert "| case_one | clean | 0 | 0 | 0 | 0/0 | 1,100 | n/a | 2.0s |  |" in report


def test_embed_requires_markers() -> None:
    with pytest.raises(ValueError, match="markers"):
        embed_in_readme("# no markers\n", "table")


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        (
            {"LLM_PROVIDER": "openai_compat", "LLM_MODEL": "qwen2.5-coder:7b",
             "OPENAI_COMPAT_BASE_URL": "http://localhost:11434/v1"},
            "OpenAI-compatible endpoint (local), min confidence 0.5",
        ),
        ({"LLM_PROVIDER": "anthropic", "LLM_EFFORT": "high"}, "Anthropic API, effort high"),
    ],
)  # fmt: skip
def test_report_states_how_results_were_produced(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], expected: str
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    description = run_module._describe_settings(CoreSettings(_env_file=None))

    assert description.startswith(expected)


def test_unpriced_models_have_no_invented_cost() -> None:
    info = RunInfo(model="qwen2.5-coder:7b", settings="local", date="d")

    table = summary_table([_result("a", True, Counts(), cost=None)], info)

    assert "| Cost (list price) | n/a (local or unpriced model) |" in table
    assert "$" not in table


async def test_rule_findings_are_scored_apart_from_the_llm_agents() -> None:
    case = next(c for c in CASES if c.name == "sec_hardcoded_api_token")

    (result,) = await run_module.evaluate([case], RoutingLLM({}), ReviewOptions(), model="m")

    # A silent model gets no credit for what the secret scan found.
    assert result.counts["security"] == Counts(fn=1)
    assert result.rule_counts == Counts(tp=1)


def test_summary_table_has_a_separate_rule_row() -> None:
    info = RunInfo(model="m", settings="s", date="d")
    result = _result("a", False, Counts(fn=1)).model_copy(
        update={"rule_counts": Counts(tp=1, fp=1)}
    )

    table = summary_table([result], info)

    assert "| security | 1 | 0 | 0 | 0 | 1 | — | 0% | — |" in table
    assert "| secret scan (rule) | — | 2 | 1 | 1 | — | 50% | — | — |" in table


def test_repeated_summary_shows_mean_and_spread() -> None:
    info = RunInfo(model="m", settings="s", date="d")
    runs = [
        [_result("a", False, Counts(tp=1, fn=1)), _result("b", True, Counts(fp=1))],
        [_result("a", False, Counts(tp=2)), _result("b", True, Counts())],
    ]

    table = repeated_summary(runs, info)

    assert "2 cases, 1 of them clean · 2 runs, mean (min-max) · d" in table
    # Precision 50% then 100%; recall 50% then 100%; F1 50% then 100%.
    assert "| security | 2 | 2 | 1.5 (1-2) | 0.5 (0-1) | 0.5 (0-1) | 75% (50%-100%) |" in (table)
    assert "False positives on the 1 clean cases per run: 0.5 (0-1) from the LLM agents" in table


def test_repeated_report_lists_each_run_per_case() -> None:
    info = RunInfo(model="m", settings="s", date="d")
    runs = [[_result("a", False, Counts(tp=1))], [_result("a", False, Counts(fn=1))]]

    report = full_repeated_report(runs, info)

    assert "`uv run python -m eval.run --repeat 2`" in report
    assert "| a | 1 | 1/0/0 · 0/0/1 | 0/0 · 0/0 |  |" in report


async def test_main_repeats_and_reports_the_spread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = RoutingLLM(dict.fromkeys(("security", "performance", "tests"), oracle))

    @asynccontextmanager
    async def fake_provider(settings: Any) -> AsyncIterator[LLMProvider]:
        yield llm

    monkeypatch.setattr(run_module, "open_llm_provider", fake_provider)
    output = tmp_path / "results.md"

    code = await run_module.main(
        ["--case", CASES[0].name, "--repeat", "2", "--output", str(output)]
    )

    assert code == 0
    assert "2 runs, mean (min-max)" in output.read_text(encoding="utf-8")
    assert len(llm.calls) == 2 * 3  # one case, three agents, twice


async def test_repeat_must_be_positive() -> None:
    assert await run_module.main(["--repeat", "0"]) == 2
