import re

import pytest

from reviewcrew.diff.chunker import (
    MIN_CHUNK_TOKENS,
    TRUNCATION_MARKER,
    DiffChunk,
    build_chunks,
    render_line,
)
from reviewcrew.diff.filters import filter_files
from reviewcrew.diff.models import DiffHunk, DiffLine, FileDiff
from reviewcrew.diff.parser import parse_diff
from reviewcrew.diff.tokens import estimate_tokens
from tests.helpers import load_diff


def _synthetic_file(path: str, hunk_sizes: list[int], *, line_width: int = 40) -> FileDiff:
    """A file whose added lines each carry a unique marker `<path>#<hunk>.<line>`."""
    hunks = []
    next_line = 1
    for hunk_index, size in enumerate(hunk_sizes):
        lines = tuple(
            DiffLine(
                kind="added",
                content=f"{path}#{hunk_index}.{i} ".ljust(line_width, "x"),
                old_lineno=None,
                new_lineno=next_line + i,
            )
            for i in range(size)
        )
        hunks.append(
            DiffHunk(
                old_start=0,
                old_length=0,
                new_start=next_line,
                new_length=size,
                section="",
                lines=lines,
            )
        )
        next_line += size + 10
    return FileDiff(path=path, status="added", hunks=tuple(hunks))


def _markers(chunks: list[DiffChunk]) -> list[str]:
    return [m for chunk in chunks for m in re.findall(r"\S+#\d+\.\d+", chunk.text)]


def _assert_within_budget(chunks: list[DiffChunk], max_tokens: int) -> None:
    for chunk in chunks:
        assert chunk.estimated_tokens == estimate_tokens(chunk.text)
        assert chunk.estimated_tokens <= max_tokens


def test_small_diff_fits_in_one_chunk() -> None:
    kept = filter_files(parse_diff(load_diff("mixed.diff"))).kept

    (chunk,) = build_chunks(kept, max_tokens=8000)

    assert chunk.index == 0
    assert chunk.paths == tuple(file.path for file in kept)
    assert "=== FILE: src/app.py (modified) ===" in chunk.text
    assert "@@ -1,8 +1,9 @@" in chunk.text
    assert "     2 + line 2 changed" in chunk.text
    assert "       - line 2" in chunk.text  # removed lines have no new line number
    assert "     1   line 1" in chunk.text


def test_render_line_formats() -> None:
    assert render_line(DiffLine(kind="added", content="x", old_lineno=None, new_lineno=12)) == (
        "    12 + x"
    )
    assert render_line(DiffLine(kind="removed", content="y", old_lineno=3, new_lineno=None)) == (
        "       - y"
    )


def test_rename_is_shown_in_the_file_header() -> None:
    file = _synthetic_file("new.py", [1]).model_copy(
        update={"status": "renamed", "old_path": "old.py"}
    )

    (chunk,) = build_chunks([file], max_tokens=MIN_CHUNK_TOKENS)

    assert chunk.text.startswith("=== FILE: new.py (renamed from old.py) ===")


@pytest.mark.parametrize("max_tokens", [MIN_CHUNK_TOKENS, 1500, 4000, 8000])
def test_chunks_never_exceed_the_limit_and_lose_no_lines(max_tokens: int) -> None:
    files = [
        *(_synthetic_file(f"src/mod{i}.py", [30, 50, 20]) for i in range(25)),
        _synthetic_file("src/huge_hunk.py", [2000]),  # one hunk far larger than any chunk
        _synthetic_file("src/wide.py", [5], line_width=200),
    ]

    chunks = build_chunks(files, max_tokens=max_tokens)

    _assert_within_budget(chunks, max_tokens)
    expected = [line.content.split()[0] for f in files for h in f.hunks for line in h.lines]
    assert _markers(chunks) == expected  # every line exactly once, in order
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_small_files_share_a_chunk_and_are_never_split() -> None:
    files = [_synthetic_file(f"f{i}.py", [10]) for i in range(6)]

    chunks = build_chunks(files, max_tokens=MIN_CHUNK_TOKENS)

    assert len(chunks) > 1
    for file in files:
        holding = [c for c in chunks if file.path in c.paths]
        assert len(holding) == 1, f"{file.path} was split although it fits in one chunk"


def test_large_file_is_split_at_hunk_boundaries_with_continuation_headers() -> None:
    # Each 40-line hunk fits a chunk on its own (~2000 chars), but two do not.
    file = _synthetic_file("big.py", [40, 40, 40])

    chunks = build_chunks([file], max_tokens=MIN_CHUNK_TOKENS)

    assert len(chunks) == 3
    assert chunks[0].text.startswith("=== FILE: big.py (added) ===")
    for chunk, hunk in zip(chunks[1:], file.hunks[1:], strict=True):
        assert chunk.text.startswith("=== FILE: big.py (added, continued) ===")
        assert hunk.header in chunk.text


def test_oversized_hunk_is_split_by_lines() -> None:
    file = _synthetic_file("huge.py", [1000])

    chunks = build_chunks([file], max_tokens=MIN_CHUNK_TOKENS)

    assert len(chunks) > 1
    assert all("(continued)" in chunk.text for chunk in chunks[1:])
    _assert_within_budget(chunks, MIN_CHUNK_TOKENS)


def test_overlong_line_is_truncated_to_fit() -> None:
    file = _synthetic_file("minified.js", [1], line_width=50_000)

    (chunk,) = build_chunks([file], max_tokens=MIN_CHUNK_TOKENS)

    assert chunk.text.endswith(TRUNCATION_MARKER)
    assert "minified.js#0.0" in chunk.text
    _assert_within_budget([chunk], MIN_CHUNK_TOKENS)


def test_head_contents_add_surrounding_context() -> None:
    kept = filter_files(parse_diff(load_diff("mixed.diff"))).kept
    new_contents = {"src/new_file.py": "import os\n\nAPI_KEY = os.environ['KEY']\n"}
    app_new = [f"line {i}" for i in range(1, 41)]
    app_new[1] = "line 2 changed"
    app_new.insert(5, "inserted after 5")
    del app_new[20]
    app_new[35] = "line near end changed"
    new_contents["src/app.py"] = "\n".join(app_new)

    without = build_chunks(kept, max_tokens=8000)[0].text
    with_context = build_chunks(kept, max_tokens=8000, new_contents=new_contents, context_lines=2)[
        0
    ].text

    assert "    11   line 10" not in without
    assert "    11   line 10" in with_context  # new line 11 = old line 10 (insert at 6)


def test_no_files_means_no_chunks() -> None:
    assert build_chunks([], max_tokens=MIN_CHUNK_TOKENS) == []


def test_too_small_budget_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_tokens"):
        build_chunks([], max_tokens=MIN_CHUNK_TOKENS - 1)
