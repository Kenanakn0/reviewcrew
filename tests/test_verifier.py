import pytest

from reviewcrew.agents.models import Finding
from reviewcrew.diff.processor import ProcessedDiff, process_diff
from reviewcrew.pipeline.verifier import verify
from tests.helpers import load_diff


@pytest.fixture(scope="module")
def diff() -> ProcessedDiff:
    # mixed.diff: src/app.py has hunks on new lines 1-9, 18-23 and 33-39.
    return process_diff(load_diff("mixed.diff"))


def finding(path: str = "src/app.py", line: int = 2, end_line: int | None = None) -> Finding:
    return Finding(
        agent="security",
        path=path,
        line=line,
        end_line=end_line,
        severity="high",
        confidence=0.9,
        title="t",
        explanation="e",
    )


def test_line_in_the_diff_is_inline(diff: ProcessedDiff) -> None:
    result = verify([finding(line=6)], diff)

    (item,) = result.inline
    assert (item.line, item.start_line) == (6, None)


def test_context_lines_inside_a_hunk_are_commentable(diff: ProcessedDiff) -> None:
    assert verify([finding(line=1)], diff).inline  # unchanged line, but part of the hunk


@pytest.mark.parametrize("line", [10, 17, 24, 40, 999])
def test_lines_outside_the_hunks_move_to_the_summary(diff: ProcessedDiff, line: int) -> None:
    result = verify([finding(line=line)], diff)

    assert result.inline == ()
    assert [f.line for f in result.outside] == [line]


def test_multi_line_within_one_hunk(diff: ProcessedDiff) -> None:
    (item,) = verify([finding(line=2, end_line=6)], diff).inline

    assert (item.start_line, item.line) == (2, 6)


def test_multi_line_across_hunks_is_reduced_to_its_first_line(diff: ProcessedDiff) -> None:
    (item,) = verify([finding(line=6, end_line=20)], diff).inline

    assert (item.start_line, item.line) == (None, 6)


def test_unknown_and_skipped_files_are_dropped(diff: ProcessedDiff) -> None:
    result = verify([finding(path="nope.py"), finding(path="package-lock.json", line=2)], diff)

    assert (result.inline, result.outside, result.unknown_file) == ((), (), 2)


def test_order_is_preserved(diff: ProcessedDiff) -> None:
    result = verify([finding(line=36), finding(line=2), finding(line=20)], diff)

    assert [item.line for item in result.inline] == [36, 2, 20]
