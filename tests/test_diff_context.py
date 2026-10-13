from collections.abc import Sequence

import pytest

from reviewcrew.diff.context import expand_hunks
from reviewcrew.diff.models import DiffHunk, FileDiff
from reviewcrew.diff.parser import parse_diff
from tests.helpers import load_diff


def _app_versions() -> tuple[list[str], list[str]]:
    """Old and new contents of src/app.py in the mixed.diff fixture."""
    old = [f"line {i}" for i in range(1, 41)]
    new = list(old)
    new[1] = "line 2 changed"
    new.insert(5, "inserted after 5")
    del new[20]
    new[35] = "line near end changed"
    return old, new


def _assert_consistent(hunks: Sequence[DiffHunk], old: list[str], new: list[str]) -> None:
    """Every line's content matches the file version its line numbers point into."""
    seen_new: list[int] = []
    for hunk in hunks:
        for line in hunk.lines:
            if line.new_lineno is not None:
                assert new[line.new_lineno - 1] == line.content
                seen_new.append(line.new_lineno)
            if line.old_lineno is not None:
                assert old[line.old_lineno - 1] == line.content
    assert seen_new == sorted(set(seen_new)), "lines must be unique and in order"


@pytest.fixture
def app() -> FileDiff:
    return next(f for f in parse_diff(load_diff("mixed.diff")) if f.path == "src/app.py")


@pytest.mark.parametrize("context_lines", [1, 3, 5, 20])
def test_expanded_lines_match_both_file_versions(app: FileDiff, context_lines: int) -> None:
    old, new = _app_versions()

    expanded = expand_hunks(app, "\n".join(new) + "\n", context_lines)

    _assert_consistent(expanded, old, new)


def test_expansion_adds_lines_around_each_hunk(app: FileDiff) -> None:
    _, new = _app_versions()

    expanded = expand_hunks(app, "\n".join(new), context_lines=3)

    assert [(h.new_start, h.new_length) for h in expanded] == [(1, 12), (15, 12), (30, 11)]
    # The original diff lines are untouched; only context was added.
    assert all(
        sum(1 for line in h.lines if line.kind != "context")
        == sum(1 for line in o.lines if line.kind != "context")
        for h, o in zip(expanded, app.hunks, strict=True)
    )


def test_large_context_never_duplicates_lines_between_hunks(app: FileDiff) -> None:
    _, new = _app_versions()

    expanded = expand_hunks(app, "\n".join(new), context_lines=100)

    right_side = [line.new_lineno for h in expanded for line in h.lines if line.new_lineno]
    assert right_side == list(range(1, len(new) + 1))


def test_zero_context_returns_original_hunks(app: FileDiff) -> None:
    assert expand_hunks(app, "anything", context_lines=0) == app.hunks


def test_pure_insertion_and_deletion_hunks() -> None:
    # Old file: "line 1".."line 10". Delete line 5, insert "new 8" after old line 8 (-U0).
    diff = (
        "diff --git a/f.txt b/f.txt\n--- a/f.txt\n+++ b/f.txt\n"
        "@@ -5 +4,0 @@\n-line 5\n"
        "@@ -8,0 +8 @@\n+new 8\n"
    )
    old = [f"line {i}" for i in range(1, 11)]
    new = [*old[:4], *old[5:8], "new 8", *old[8:]]
    (file,) = parse_diff(diff)

    expanded = expand_hunks(file, "\n".join(new), context_lines=2)

    _assert_consistent(expanded, old, new)
    first = [(line.kind, line.old_lineno, line.new_lineno) for line in expanded[0].lines]
    assert first == [
        ("context", 3, 3),
        ("context", 4, 4),
        ("removed", 5, None),
        ("context", 6, 5),
        ("context", 7, 6),
    ]
    second = [(line.kind, line.old_lineno, line.new_lineno) for line in expanded[1].lines]
    assert second == [
        ("context", 8, 7),
        ("added", None, 8),
        ("context", 9, 9),
        ("context", 10, 10),
    ]


def test_commentable_lines_are_not_affected_by_expansion(app: FileDiff) -> None:
    _, new = _app_versions()
    before = app.commentable_lines

    expand_hunks(app, "\n".join(new), context_lines=10)

    assert app.commentable_lines == before
