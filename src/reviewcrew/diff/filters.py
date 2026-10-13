"""Drop files that are not worth sending to the review agents."""

from collections.abc import Sequence
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from reviewcrew.diff.models import FileDiff
from reviewcrew.repo_config.globs import matches_any

SkipReason = Literal[
    "removed",
    "binary",
    "submodule",
    "symlink",
    "no_changes",
    "lock_file",
    "minified",
    "generated",
    "too_large",
    "ignored",
]

DEFAULT_LOCK_FILES = frozenset(
    {
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lock",
        "bun.lockb",
        "poetry.lock",
        "Pipfile.lock",
        "pdm.lock",
        "uv.lock",
        "Cargo.lock",
        "Gemfile.lock",
        "composer.lock",
        "go.sum",
        "mix.lock",
        "pubspec.lock",
        "Podfile.lock",
        "packages.lock.json",
        "flake.lock",
    }
)
DEFAULT_MINIFIED_GLOBS = ("*.min.js", "*.min.css", "*.min.mjs", "*.js.map", "*.css.map")
DEFAULT_GENERATED_DIRS = frozenset(
    {"dist", "build", "vendor", "node_modules", "generated", "__generated__", ".next"}
)
DEFAULT_GENERATED_GLOBS = (
    "*_pb2.py",
    "*_pb2.pyi",
    "*_pb2_grpc.py",
    "*.pb.go",
    "*.generated.*",
    "*.g.dart",
    "*.designer.cs",
)


class FilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    lock_files: frozenset[str] = DEFAULT_LOCK_FILES
    minified_globs: tuple[str, ...] = DEFAULT_MINIFIED_GLOBS
    generated_dirs: frozenset[str] = DEFAULT_GENERATED_DIRS
    generated_globs: tuple[str, ...] = DEFAULT_GENERATED_GLOBS
    # Files with more added + removed lines than this are skipped as too large to review.
    max_changed_lines: int = Field(default=1000, ge=1)
    # Extra patterns from the repository's `.reviewcrew.yml` (see repo_config.globs).
    ignore_globs: tuple[str, ...] = ()


class SkippedFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    reason: SkipReason


class FilterResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    kept: tuple[FileDiff, ...]
    skipped: tuple[SkippedFile, ...]


def skip_reason(file: FileDiff, config: FilterConfig) -> SkipReason | None:
    """Return why `file` should not be reviewed, or `None` to keep it."""
    path = PurePosixPath(file.path)
    name = path.name

    if file.status == "removed":
        return "removed"
    if config.ignore_globs and matches_any(file.path, config.ignore_globs):
        return "ignored"
    if file.is_binary:
        return "binary"
    if file.is_submodule:
        return "submodule"
    if file.is_symlink:
        return "symlink"
    if name in config.lock_files:
        return "lock_file"
    if any(fnmatchcase(name, glob) for glob in config.minified_globs):
        return "minified"
    if any(part in config.generated_dirs for part in path.parent.parts) or any(
        fnmatchcase(name, glob) for glob in config.generated_globs
    ):
        return "generated"
    if not file.hunks:
        # Pure renames and mode changes carry no content. Deletion-only edits are kept:
        # removing a check can be exactly what a reviewer needs to see.
        return "no_changes"
    if file.added_count + file.removed_count > config.max_changed_lines:
        return "too_large"
    return None


def filter_files(files: Sequence[FileDiff], config: FilterConfig | None = None) -> FilterResult:
    """Split `files` into those to review and those skipped (with the reason)."""
    config = config or FilterConfig()
    kept: list[FileDiff] = []
    skipped: list[SkippedFile] = []
    for file in files:
        reason = skip_reason(file, config)
        if reason is None:
            kept.append(file)
        else:
            skipped.append(SkippedFile(path=file.path, reason=reason))
    return FilterResult(kept=tuple(kept), skipped=tuple(skipped))
