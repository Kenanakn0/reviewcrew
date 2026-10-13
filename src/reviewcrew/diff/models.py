"""Typed representation of a parsed pull request diff."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

LineKind = Literal["added", "removed", "context"]
FileStatus = Literal["added", "modified", "removed", "renamed"]


class DiffLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: LineKind
    content: str
    old_lineno: int | None  # None for added lines
    new_lineno: int | None  # None for removed lines


class DiffHunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    old_start: int
    old_length: int
    new_start: int
    new_length: int
    section: str  # text after the second `@@`, usually the enclosing function
    lines: tuple[DiffLine, ...]

    @property
    def header(self) -> str:
        header = f"@@ -{self.old_start},{self.old_length} +{self.new_start},{self.new_length} @@"
        return f"{header} {self.section}" if self.section else header


class FileDiff(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str  # new path (old path for removed files)
    old_path: str | None = None  # set for renames only
    status: FileStatus
    is_binary: bool = False
    is_submodule: bool = False
    is_symlink: bool = False
    hunks: tuple[DiffHunk, ...] = ()

    @property
    def added_count(self) -> int:
        return sum(1 for hunk in self.hunks for line in hunk.lines if line.kind == "added")

    @property
    def removed_count(self) -> int:
        return sum(1 for hunk in self.hunks for line in hunk.lines if line.kind == "removed")

    @property
    def added_lines(self) -> frozenset[int]:
        """New-file line numbers introduced by this diff."""
        return frozenset(
            line.new_lineno
            for hunk in self.hunks
            for line in hunk.lines
            if line.kind == "added" and line.new_lineno is not None
        )

    @property
    def commentable_lines(self) -> frozenset[int]:
        """New-file lines GitHub accepts for `side=RIGHT` review comments (added + context)."""
        return frozenset(
            line.new_lineno
            for hunk in self.hunks
            for line in hunk.lines
            if line.new_lineno is not None
        )

    def hunk_for_line(self, new_lineno: int) -> DiffHunk | None:
        """Return the hunk whose right side contains `new_lineno`, if any."""
        for hunk in self.hunks:
            if any(line.new_lineno == new_lineno for line in hunk.lines):
                return hunk
        return None
