import pytest

from reviewcrew.diff.models import FileDiff
from reviewcrew.diff.parser import DiffParseError, parse_diff
from tests.helpers import load_diff


@pytest.fixture(scope="module")
def files() -> dict[str, FileDiff]:
    return {file.path: file for file in parse_diff(load_diff("mixed.diff"))}


def test_every_file_is_parsed_with_its_status(files: dict[str, FileDiff]) -> None:
    assert {path: file.status for path, file in files.items()} == {
        "dist/bundle.js": "modified",
        "docs/ünïcode name.md": "modified",
        "logo.png": "modified",
        "package-lock.json": "modified",
        "src/app.py": "modified",
        "src/new_file.py": "added",
        "src/new_name.py": "renamed",
        "src/no_newline.txt": "modified",
        "src/removed.py": "removed",
        "static.min.js": "modified",
        "vendor/lib/thing.go": "modified",
    }


def test_new_line_numbers_map_to_their_content(files: dict[str, FileDiff]) -> None:
    app = files["src/app.py"]
    by_new_line = {
        line.new_lineno: line.content
        for hunk in app.hunks
        for line in hunk.lines
        if line.new_lineno is not None
    }

    assert app.added_lines == {2, 6, 36}
    assert by_new_line[2] == "line 2 changed"
    assert by_new_line[6] == "inserted after 5"
    assert by_new_line[36] == "line near end changed"
    # After the insertion at 6 and the removal of old line 20, the offsets cancel out.
    assert by_new_line[7] == "line 6"
    assert by_new_line[21] == "line 21"


def test_removed_lines_keep_only_their_old_line_number(files: dict[str, FileDiff]) -> None:
    removed = [
        line for hunk in files["src/app.py"].hunks for line in hunk.lines if line.kind == "removed"
    ]

    assert [(line.content, line.old_lineno, line.new_lineno) for line in removed] == [
        ("line 2", 2, None),
        ("line 20", 20, None),
        ("line 36", 36, None),
    ]


def test_commentable_lines_are_the_right_side_of_each_hunk(files: dict[str, FileDiff]) -> None:
    app = files["src/app.py"]

    assert [(h.new_start, h.new_length) for h in app.hunks] == [(1, 9), (18, 6), (33, 7)]
    assert app.commentable_lines == set(range(1, 10)) | set(range(18, 24)) | set(range(33, 40))


@pytest.mark.parametrize(("line", "hunk_start"), [(1, 1), (9, 1), (20, 18), (39, 33)])
def test_hunk_for_line_finds_the_enclosing_hunk(
    files: dict[str, FileDiff], line: int, hunk_start: int
) -> None:
    hunk = files["src/app.py"].hunk_for_line(line)

    assert hunk is not None
    assert hunk.new_start == hunk_start


@pytest.mark.parametrize("line", [10, 17, 24, 32, 40])
def test_hunk_for_line_outside_the_diff_is_none(files: dict[str, FileDiff], line: int) -> None:
    assert files["src/app.py"].hunk_for_line(line) is None


def test_hunk_section_header_is_kept(files: dict[str, FileDiff]) -> None:
    assert files["src/app.py"].hunks[1].header == "@@ -17,7 +18,6 @@ line 16"


def test_added_file(files: dict[str, FileDiff]) -> None:
    new_file = files["src/new_file.py"]

    assert new_file.added_lines == {1, 2, 3}
    assert new_file.hunks[0].lines[2].content == "API_KEY = os.environ['KEY']"


def test_removed_file_has_no_commentable_lines(files: dict[str, FileDiff]) -> None:
    removed = files["src/removed.py"]

    assert removed.removed_count == 2
    assert removed.commentable_lines == frozenset()


def test_pure_rename_records_old_path_and_has_no_hunks(files: dict[str, FileDiff]) -> None:
    renamed = files["src/new_name.py"]

    assert renamed.old_path == "src/old_name.py"
    assert renamed.hunks == ()


def test_binary_file_is_flagged(files: dict[str, FileDiff]) -> None:
    assert files["logo.png"].is_binary
    assert files["logo.png"].hunks == ()


def test_quoted_unicode_path_is_decoded(files: dict[str, FileDiff]) -> None:
    assert files["docs/ünïcode name.md"].added_lines == {2}


def test_no_newline_marker_is_not_a_line(files: dict[str, FileDiff]) -> None:
    lines = files["src/no_newline.txt"].hunks[0].lines

    assert [(line.kind, line.content) for line in lines] == [
        ("context", "alpha"),
        ("removed", "beta"),
        ("added", "beta"),
        ("added", "gamma"),
    ]


def test_crlf_line_endings_are_stripped() -> None:
    diff = "diff --git a/w.txt b/w.txt\r\n--- a/w.txt\r\n+++ b/w.txt\r\n@@ -1 +1 @@\r\n-a\r\n+b\r\n"

    (file,) = parse_diff(diff)

    assert [line.content for line in file.hunks[0].lines] == ["a", "b"]


def test_empty_diff_has_no_files() -> None:
    assert parse_diff("") == []


@pytest.mark.parametrize(
    "diff",
    [
        "--- a/x\n+++ b/x\n@@ -1,3 +1,3 @@\n-a\n",  # hunk shorter than its header says
        "@@ -1 +1 @@\n-a\n+b\n",  # hunk without a file header
    ],
)
def test_malformed_diff_raises(diff: str) -> None:
    with pytest.raises(DiffParseError):
        parse_diff(diff)
