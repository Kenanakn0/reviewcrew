"""Test reviewer: changed logic without tests and untested edge cases."""

import re
from typing import ClassVar

from reviewcrew.agents.base import BaseAgent
from reviewcrew.agents.models import AgentName
from reviewcrew.diff.chunker import DiffChunk
from reviewcrew.diff.definitions import CoverageHints, Definition

# Paths come from the PR; keep them to one short, plain line inside the bot's own notes.
_UNSAFE_PATH_CHARS = re.compile(r"[^\w./\-]")
MAX_NOTE_PATH = 120
MAX_NOTE_TEST_PATHS = 10
NOTES_HEADER = (
    "ReviewCrew pre-analysis (computed by the bot from the diff, not written by the PR author):"
)


def _safe_path(path: str) -> str:
    return _UNSAFE_PATH_CHARS.sub("_", path)[:MAX_NOTE_PATH]


def _item(definition: Definition) -> str:
    return (
        f"- {definition.name} ({_safe_path(definition.path)}, line {definition.line}, "
        f"{definition.change})"
    )


class TestAgent(BaseAgent):
    __test__ = False  # not a pytest test class despite the name

    name: ClassVar[AgentName] = "tests"
    role: ClassVar[str] = "a senior engineer who specialises in testing"
    focus: ClassVar[str] = "missing or ineffective tests for the changed logic"
    enforce_category: ClassVar[bool] = True

    def notes(self, chunk: DiffChunk, *, coverage: CoverageHints | None) -> str:
        if coverage is None:
            return ""
        untested = [d for d in coverage.untested if d.path in chunk.paths]
        covered = [d for d in coverage.covered if d.path in chunk.paths]
        lines: list[str] = []
        if untested:
            lines += [
                "These functions or classes are added or changed in this part, and no test "
                "file in this pull request mentions them:",
                *map(_item, untested),
                "Report each one that contains real logic as `No tests for <name>` at that "
                "line. Skip only trivial ones.",
            ]
        if covered:
            tests = ", ".join(map(_safe_path, coverage.test_paths[:MAX_NOTE_TEST_PATHS]))
            lines += [
                f"These are mentioned by the test files in this pull request ({tests}):",
                *map(_item, covered),
                "Do not report them as untested. Judge those tests instead: can they fail "
                "(real assertions, not only on mocks)? Do they cover failure paths, invalid "
                "input and boundaries?",
            ]
        return "\n".join([NOTES_HEADER, *lines]) if lines else ""
