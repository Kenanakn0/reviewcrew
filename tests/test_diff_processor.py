import pytest

from reviewcrew.diff.filters import FilterConfig
from reviewcrew.diff.processor import DiffOptions, process_diff
from tests.helpers import load_diff


def test_process_mixed_fixture() -> None:
    diff = process_diff(load_diff("mixed.diff"))

    assert diff.total_files == 11
    assert sorted(diff.files) == [
        "docs/ünïcode name.md",
        "src/app.py",
        "src/new_file.py",
        "src/no_newline.txt",
    ]
    assert len(diff.skipped) == 7
    assert len(diff.chunks) == 1
    assert set(diff.chunks[0].paths) == set(diff.files)


@pytest.mark.parametrize(
    ("path", "line", "expected"),
    [
        ("src/app.py", 2, True),  # added line
        ("src/app.py", 1, True),  # context line inside a hunk
        ("src/app.py", 12, False),  # between hunks
        ("src/new_file.py", 3, True),
        ("package-lock.json", 2, False),  # skipped file
        ("does/not/exist.py", 1, False),
    ],
)
def test_is_commentable(path: str, line: int, expected: bool) -> None:
    diff = process_diff(load_diff("mixed.diff"))

    assert diff.is_commentable(path, line) is expected


def test_options_are_applied() -> None:
    options = DiffOptions(filters=FilterConfig(max_changed_lines=1))

    diff = process_diff(load_diff("mixed.diff"), options)

    assert "src/app.py" not in diff.files
    assert ("src/app.py", "too_large") in {(s.path, s.reason) for s in diff.skipped}
