"""Render reviewable files as text and split them into token-bounded chunks for the agents.

Rendered format (new-file line numbers let agents cite `line` for RIGHT-side comments):

    === FILE: src/app.py (modified) ===
    @@ -1,3 +1,4 @@ def main():
         1   unchanged line
           - removed line
         2 + added line
"""

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from reviewcrew.diff.context import expand_hunks
from reviewcrew.diff.models import DiffHunk, DiffLine, FileDiff
from reviewcrew.diff.tokens import char_budget, estimate_tokens

# Below this the fixed headers alone could exhaust the budget.
MIN_CHUNK_TOKENS = 1000
MAX_PATH_DISPLAY = 300
MAX_HUNK_HEADER_DISPLAY = 200
CHUNK_SEPARATOR = "\n\n"
TRUNCATION_MARKER = " …[truncated]"

_MARKERS = {"added": "+", "removed": "-", "context": " "}


class DiffChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int
    paths: tuple[str, ...]
    text: str
    estimated_tokens: int


def render_line(line: DiffLine) -> str:
    number = "" if line.new_lineno is None else str(line.new_lineno)
    return f"{number:>6} {_MARKERS[line.kind]} {line.content}"


def file_header(file: FileDiff, *, continued: bool = False) -> str:
    path = _clip(file.path, MAX_PATH_DISPLAY)
    details: str = file.status
    if file.old_path is not None:
        details += f" from {_clip(file.old_path, MAX_PATH_DISPLAY)}"
    if continued:
        details += ", continued"
    return f"=== FILE: {path} ({details}) ==="


def _hunk_header(hunk: DiffHunk, *, continued: bool = False) -> str:
    header = _clip(hunk.header, MAX_HUNK_HEADER_DISPLAY)
    return f"{header} (continued)" if continued else header


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class _BlockBuilder:
    """Accumulates the lines of one file into blocks that each fit the character budget."""

    def __init__(self, file: FileDiff, budget: int) -> None:
        self._file = file
        self._budget = budget
        self.blocks: list[str] = []
        self._lines: list[str] = []
        self._size = -1  # joining n lines adds n - 1 newlines
        self._has_body = False
        self._start_block(file_header(file))

    def _start_block(self, header: str) -> None:
        self._lines = []
        self._size = -1
        self._has_body = False
        self._append([header])

    def _fits(self, extra: Sequence[str]) -> bool:
        return self._size + sum(len(line) + 1 for line in extra) <= self._budget

    def _append(self, lines: Sequence[str]) -> None:
        self._lines.extend(lines)
        self._size += sum(len(line) + 1 for line in lines)

    def flush(self) -> None:
        if self._has_body:  # never emit a block that holds only headers
            self.blocks.append("\n".join(self._lines))
        self._start_block(file_header(self._file, continued=True))

    def add_hunk(self, hunk: DiffHunk) -> None:
        rendered = [_hunk_header(hunk), *(render_line(line) for line in hunk.lines)]
        if not self._fits(rendered):
            self.flush()
        if self._fits(rendered):
            self._append(rendered)
            self._has_body = True
            return
        # The hunk is too large even for an empty block: split it line by line.
        self._append([_hunk_header(hunk)])
        continued_header = _hunk_header(hunk, continued=True)
        for line in rendered[1:]:
            if not self._fits([line]):
                if self._has_body:
                    self.flush()
                    self._append([continued_header])
                line = self._truncate(line)
            self._append([line])
            self._has_body = True

    def _truncate(self, line: str) -> str:
        room = self._budget - self._size - 1  # minus the newline before the line
        if len(line) <= room:
            return line
        return line[: max(room - len(TRUNCATION_MARKER), 0)] + TRUNCATION_MARKER


def _file_blocks(file: FileDiff, hunks: Sequence[DiffHunk], budget: int) -> list[str]:
    builder = _BlockBuilder(file, budget)
    for hunk in hunks:
        builder.add_hunk(hunk)
    builder.flush()
    return builder.blocks


def build_chunks(
    files: Sequence[FileDiff],
    *,
    max_tokens: int,
    new_contents: Mapping[str, str] | None = None,
    context_lines: int = 0,
) -> list[DiffChunk]:
    """Pack `files` into chunks whose estimated token count never exceeds `max_tokens`.

    Files stay whole when they fit; otherwise they are split at hunk boundaries, and a
    single oversized hunk is split by lines (an overlong line is truncated). When
    `new_contents` has a file's head version, each hunk gets up to `context_lines`
    extra surrounding lines.
    """
    if max_tokens < MIN_CHUNK_TOKENS:
        raise ValueError(f"max_tokens must be at least {MIN_CHUNK_TOKENS}")
    budget = char_budget(max_tokens)

    blocks: list[tuple[str, str]] = []
    for file in files:
        content = (new_contents or {}).get(file.path)
        hunks = file.hunks if content is None else expand_hunks(file, content, context_lines)
        blocks.extend((file.path, block) for block in _file_blocks(file, hunks, budget))

    chunks: list[DiffChunk] = []
    current: list[tuple[str, str]] = []
    size = 0

    def close() -> None:
        text = CHUNK_SEPARATOR.join(block for _, block in current)
        paths = tuple(dict.fromkeys(path for path, _ in current))
        chunks.append(
            DiffChunk(
                index=len(chunks), paths=paths, text=text, estimated_tokens=estimate_tokens(text)
            )
        )

    for path, block in blocks:
        added = len(block) + (len(CHUNK_SEPARATOR) if current else 0)
        if current and size + added > budget:
            close()
            current, size = [], 0
            added = len(block)
        current.append((path, block))
        size += added
    if current:
        close()
    return chunks
