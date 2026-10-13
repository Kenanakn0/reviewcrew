"""Widen hunks with surrounding lines from the new version of the file."""

from reviewcrew.diff.models import DiffHunk, DiffLine, FileDiff


def _covered_range(hunk: DiffHunk) -> tuple[int, int]:
    """First and last new-file lines inside the hunk; empty (first > last) for deletions."""
    if hunk.new_length == 0:
        # `new_start` is the line *after which* the deletion happened.
        return hunk.new_start + 1, hunk.new_start
    return hunk.new_start, hunk.new_start + hunk.new_length - 1


def expand_hunks(file: FileDiff, new_content: str, context_lines: int) -> tuple[DiffHunk, ...]:
    """Return `file.hunks` widened by up to `context_lines` unchanged lines on each side.

    Extra lines come from `new_content` (the file at the PR head), never overlap a
    neighbouring hunk, and are marked as context. The result is for prompting only:
    GitHub can comment only on lines in the original hunks (`FileDiff.commentable_lines`).
    """
    if context_lines <= 0 or not file.hunks:
        return file.hunks

    source = new_content.splitlines()
    ranges = [_covered_range(hunk) for hunk in file.hunks]
    expanded: list[DiffHunk] = []
    previous_last = 0  # last new-file line already emitted
    # Outside hunks, old line = new line + net lines removed by all earlier hunks.
    delta = 0

    for index, hunk in enumerate(file.hunks):
        first, last = ranges[index]
        next_first = ranges[index + 1][0] if index + 1 < len(ranges) else len(source) + 1
        before_start = max(first - context_lines, previous_last + 1, 1)
        after_end = min(last + context_lines, next_first - 1, len(source))

        before = [_context_line(source, n, n + delta) for n in range(before_start, first)]
        delta += hunk.old_length - hunk.new_length
        after = [_context_line(source, n, n + delta) for n in range(last + 1, after_end + 1)]

        expanded.append(_with_lines(hunk, (*before, *hunk.lines, *after)))
        previous_last = max(last, after_end)

    return tuple(expanded)


def _context_line(source: list[str], new_lineno: int, old_lineno: int) -> DiffLine:
    return DiffLine(
        kind="context",
        content=source[new_lineno - 1],
        old_lineno=old_lineno,
        new_lineno=new_lineno,
    )


def _with_lines(hunk: DiffHunk, lines: tuple[DiffLine, ...]) -> DiffHunk:
    """Copy `hunk` with new `lines`, recomputing the header ranges from them."""
    old_numbers = [line.old_lineno for line in lines if line.old_lineno is not None]
    new_numbers = [line.new_lineno for line in lines if line.new_lineno is not None]
    return hunk.model_copy(
        update={
            "lines": lines,
            "old_start": min(old_numbers) if old_numbers else hunk.old_start,
            "old_length": len(old_numbers),
            "new_start": min(new_numbers) if new_numbers else hunk.new_start,
            "new_length": len(new_numbers),
        }
    )
