"""Diff processing entry point: parse -> filter -> chunk."""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from reviewcrew.diff.chunker import MIN_CHUNK_TOKENS, DiffChunk, build_chunks
from reviewcrew.diff.filters import FilterConfig, SkippedFile, filter_files
from reviewcrew.diff.models import FileDiff
from reviewcrew.diff.parser import parse_diff


class DiffOptions(BaseModel):
    model_config = ConfigDict(frozen=True)

    filters: FilterConfig = FilterConfig()
    max_tokens_per_chunk: int = Field(default=8000, ge=MIN_CHUNK_TOKENS)
    context_lines: int = Field(default=5, ge=0)


class ProcessedDiff(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_files: int
    files: dict[str, FileDiff]  # files kept for review, keyed by new path
    skipped: tuple[SkippedFile, ...]
    chunks: tuple[DiffChunk, ...]

    def is_commentable(self, path: str, line: int) -> bool:
        """Whether GitHub accepts a RIGHT-side review comment on `path:line`."""
        file = self.files.get(path)
        return file is not None and line in file.commentable_lines


def process_diff(
    text: str,
    options: DiffOptions | None = None,
    *,
    new_contents: Mapping[str, str] | None = None,
) -> ProcessedDiff:
    """Parse a PR diff, drop unreviewable files and split the rest into agent-sized chunks."""
    options = options or DiffOptions()
    parsed = parse_diff(text)
    result = filter_files(parsed, options.filters)
    chunks = build_chunks(
        result.kept,
        max_tokens=options.max_tokens_per_chunk,
        new_contents=new_contents,
        context_lines=options.context_lines,
    )
    return ProcessedDiff(
        total_files=len(parsed),
        files={file.path: file for file in result.kept},
        skipped=result.skipped,
        chunks=tuple(chunks),
    )
