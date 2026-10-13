import pytest

from reviewcrew.diff.filters import FilterConfig, filter_files, skip_reason
from reviewcrew.diff.models import DiffHunk, DiffLine, FileDiff
from reviewcrew.diff.parser import parse_diff
from tests.helpers import load_diff


def _file(path: str, *, added: int = 1, removed: int = 0) -> FileDiff:
    lines = [
        DiffLine(kind="added", content=f"a{i}", old_lineno=None, new_lineno=i + 1)
        for i in range(added)
    ] + [
        DiffLine(kind="removed", content=f"r{i}", old_lineno=i + 1, new_lineno=None)
        for i in range(removed)
    ]
    hunk = DiffHunk(
        old_start=1,
        old_length=removed,
        new_start=1,
        new_length=added,
        section="",
        lines=tuple(lines),
    )
    return FileDiff(path=path, status="modified", hunks=(hunk,))


def test_mixed_fixture_is_split_into_kept_and_skipped() -> None:
    result = filter_files(parse_diff(load_diff("mixed.diff")))

    assert [file.path for file in result.kept] == [
        "docs/ünïcode name.md",
        "src/app.py",
        "src/new_file.py",
        "src/no_newline.txt",
    ]
    assert {(s.path, s.reason) for s in result.skipped} == {
        ("dist/bundle.js", "generated"),
        ("logo.png", "binary"),
        ("package-lock.json", "lock_file"),
        ("src/new_name.py", "no_changes"),
        ("src/removed.py", "removed"),
        ("static.min.js", "minified"),
        ("vendor/lib/thing.go", "generated"),
    }


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("frontend/yarn.lock", "lock_file"),
        ("uv.lock", "lock_file"),
        ("services/api/go.sum", "lock_file"),
        ("assets/app.min.js", "minified"),
        ("assets/app.min.css", "minified"),
        ("assets/app.js.map", "minified"),
        ("web/build/index.js", "generated"),
        ("node_modules/x/index.js", "generated"),
        ("pkg/vendor/github.com/x/y.go", "generated"),
        ("proto/user_pb2.py", "generated"),
        ("api/user.pb.go", "generated"),
        ("src/schema.generated.ts", "generated"),
    ],
)
def test_unreviewable_paths_are_skipped(path: str, reason: str) -> None:
    assert skip_reason(_file(path), FilterConfig()) == reason


@pytest.mark.parametrize(
    "path",
    [
        "src/builder.py",  # "build" only matches whole directory names
        "src/dist_utils.py",
        "docs/vendor.md",  # a file named like a generated dir is fine
        "src/lock.py",
        "src/minify.js",
    ],
)
def test_similar_looking_source_paths_are_kept(path: str) -> None:
    assert skip_reason(_file(path), FilterConfig()) is None


def test_files_over_the_size_threshold_are_skipped() -> None:
    config = FilterConfig(max_changed_lines=100)

    assert skip_reason(_file("big.py", added=60, removed=40), config) is None
    assert skip_reason(_file("big.py", added=60, removed=41), config) == "too_large"


def test_deletion_only_edits_are_kept() -> None:
    # Removing a line (e.g. an auth check) is reviewable even though nothing was added.
    assert skip_reason(_file("auth.py", added=0, removed=3), FilterConfig()) is None


@pytest.mark.parametrize(
    ("flags", "reason"),
    [({"is_submodule": True}, "submodule"), ({"is_symlink": True}, "symlink")],
)
def test_submodules_and_symlinks_are_skipped(flags: dict[str, bool], reason: str) -> None:
    file = _file("ext/lib").model_copy(update=flags)

    assert skip_reason(file, FilterConfig()) == reason


def test_filter_lists_can_be_overridden() -> None:
    config = FilterConfig(lock_files=frozenset({"custom.lock"}), generated_dirs=frozenset())

    assert skip_reason(_file("custom.lock"), config) == "lock_file"
    assert skip_reason(_file("dist/app.js"), config) is None
