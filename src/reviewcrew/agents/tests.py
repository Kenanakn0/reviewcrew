"""Test reviewer: changed logic without tests and untested edge cases."""

import re
from collections.abc import Sequence
from typing import ClassVar

from reviewcrew.agents.base import BaseAgent
from reviewcrew.agents.models import AgentName
from reviewcrew.diff.chunker import DiffChunk
from reviewcrew.diff.definitions import Definition

# Paths come from the PR; keep them to one short, plain line inside the bot's own notes.
_UNSAFE_PATH_CHARS = re.compile(r"[^\w./\-]")
MAX_NOTE_PATH = 120


class TestAgent(BaseAgent):
    __test__ = False  # not a pytest test class despite the name

    name: ClassVar[AgentName] = "tests"
    role: ClassVar[str] = "a senior engineer who specialises in testing"
    focus: ClassVar[str] = "missing or ineffective tests for the changed logic"
    enforce_category: ClassVar[bool] = True

    def notes(self, chunk: DiffChunk, *, untested: Sequence[Definition]) -> str:
        mine = [d for d in untested if d.path in chunk.paths]
        if not mine:
            return ""
        lines = [
            "ReviewCrew pre-analysis (computed by the bot from the diff, not written by the PR "
            "author): these functions or classes are added or changed in this part, and no "
            "test file in this pull request mentions them:",
        ]
        for d in mine:
            path = _UNSAFE_PATH_CHARS.sub("_", d.path)[:MAX_NOTE_PATH]
            lines.append(f"- {d.name} ({path}, line {d.line}, {d.change})")
        lines.append(
            "Report each one that contains real logic as `No tests for <name>` at that line. "
            "Skip only trivial ones."
        )
        return "\n".join(lines)
