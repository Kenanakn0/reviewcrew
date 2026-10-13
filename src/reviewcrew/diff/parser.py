"""Parse a unified git diff (as returned by GitHub) into `FileDiff` models."""

import re

from unidiff.errors import UnidiffParseError
from unidiff.patch import Hunk, PatchedFile, PatchSet

from reviewcrew.diff.models import DiffHunk, DiffLine, FileDiff, FileStatus, LineKind

_LINE_KINDS: dict[str, LineKind] = {"+": "added", "-": "removed", " ": "context"}
_OCTAL_ESCAPE = re.compile(rb"\\([0-7]{3})")
_SIMPLE_ESCAPES = {b'\\"': b'"', b"\\\\": b"\\", b"\\t": b"\t", b"\\n": b"\n"}


class DiffParseError(ValueError):
    """The diff text is not a valid unified diff."""


def parse_diff(text: str) -> list[FileDiff]:
    """Parse `text` into one `FileDiff` per file, in diff order."""
    try:
        patch = PatchSet(text)
    except UnidiffParseError as exc:
        raise DiffParseError(str(exc)) from exc
    return [_convert_file(patched) for patched in patch]


def _unquote_path(path: str) -> str:
    """Undo git's C-style quoting of paths with special or non-ASCII characters."""
    if not (len(path) >= 2 and path.startswith('"') and path.endswith('"')):
        return path
    raw = path[1:-1].encode("utf-8")
    raw = _OCTAL_ESCAPE.sub(lambda m: bytes([int(m.group(1), 8)]), raw)
    for escaped, plain in _SIMPLE_ESCAPES.items():
        raw = raw.replace(escaped, plain)
    return raw.decode("utf-8", errors="replace")


def _strip_prefix(path: str) -> str:
    unquoted = _unquote_path(path)
    return unquoted[2:] if unquoted[:2] in ("a/", "b/") else unquoted


def _status(patched: PatchedFile) -> FileStatus:
    if patched.is_added_file:
        return "added"
    if patched.is_removed_file:
        return "removed"
    if patched.is_rename:
        return "renamed"
    return "modified"


def _convert_hunk(hunk: Hunk) -> DiffHunk:
    lines = tuple(
        DiffLine(
            kind=_LINE_KINDS[line.line_type],
            content=line.value.rstrip("\r\n"),
            old_lineno=line.source_line_no,
            new_lineno=line.target_line_no,
        )
        for line in hunk
        if line.line_type in _LINE_KINDS
    )
    return DiffHunk(
        old_start=hunk.source_start,
        old_length=hunk.source_length,
        new_start=hunk.target_start,
        new_length=hunk.target_length,
        section=hunk.section_header.strip(),
        lines=lines,
    )


def _convert_file(patched: PatchedFile) -> FileDiff:
    status = _status(patched)
    return FileDiff(
        path=_unquote_path(patched.path),
        old_path=_strip_prefix(patched.source_file) if status == "renamed" else None,
        status=status,
        is_binary=patched.is_binary_file,
        is_submodule=patched.is_submodule,
        is_symlink=patched.is_symlink,
        hunks=tuple(_convert_hunk(hunk) for hunk in patched),
    )
