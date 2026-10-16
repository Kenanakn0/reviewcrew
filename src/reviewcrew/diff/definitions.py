"""Find the functions and classes a diff adds or changes, and which of them no test file in
the pull request mentions. Regex based and language-agnostic enough for a hint: the test
reviewer gets the list as a fact instead of having to work it out (small models often don't).
"""

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from reviewcrew.diff.models import DiffHunk, FileDiff

_TEST_PATH = re.compile(
    r"""(?ix)
    (?:^|/)(?:tests?|__tests__|specs?)/        # a tests/ or spec/ directory
    | (?:^|/)test_[^/]*$                       # test_x.py
    | _tests?\.[a-z]+$                         # x_test.py, x_test.go
    | \.(?:test|spec)\.[a-z]+$                 # x.test.ts, x.spec.js
    | (?:^|/)[A-Z][^/]*Tests?\.(?:java|kt|cs)$ # FooTest.java, FooTests.cs
    """
)
_DEFINITIONS = [
    re.compile(p)
    for p in (
        r"^\s*(?:async\s+)?def\s+(?P<name>[A-Za-z_]\w*)\s*\(",  # Python
        r"^\s*class\s+(?P<name>[A-Za-z_]\w*)",  # Python, JS/TS, Java, ...
        # JS/TS function declarations and arrow functions bound to a name.
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(?P<name>[A-Za-z_$][\w$]*)",
        r"^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
        r"(?:async\s+)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>",
        r"^func\s+(?:\([^)]*\)\s*)?(?P<name>[A-Za-z_]\w*)\s*\(",  # Go
    )
]
MAX_DEFINITIONS = 30  # listed in one hint; more would crowd the prompt


class Definition(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    name: str
    line: int  # the header line, or the first changed line when the header is not shown
    change: Literal["added", "changed"]


def is_test_path(path: str) -> bool:
    return _TEST_PATH.search(path) is not None


def definition_name(text: str) -> str | None:
    for pattern in _DEFINITIONS:
        if (match := pattern.match(text)) is not None:
            return match.group("name")
    return None


def _skip(name: str) -> bool:
    # Dunder methods and the tests themselves are not "logic to test".
    return (name.startswith("__") and name.endswith("__")) or name.lower().startswith("test")


def _hunk_definitions(path: str, hunk: DiffHunk) -> list[Definition]:
    """Definitions whose header is added, plus the enclosing definition of changed lines."""
    found: list[Definition] = []
    # Hunk headers often name the enclosing definition ("@@ ... @@ def handler(request):").
    current = definition_name(hunk.section)
    current_line: int | None = None
    current_changed = False
    next_new = hunk.new_start  # new-file position of the next line, also for removed ones
    for line in hunk.lines:
        position = line.new_lineno or next_new
        if line.new_lineno is not None:
            next_new = line.new_lineno + 1
        name = definition_name(line.content) if line.kind != "removed" else None
        if name is not None:
            current, current_line, current_changed = name, position, False
            if line.kind == "added":
                found.append(Definition(path=path, name=name, line=position, change="added"))
                current_changed = True  # already listed as added
            continue
        if line.kind == "context" or current is None or current_changed:
            continue
        anchor = current_line or position
        found.append(Definition(path=path, name=current, line=anchor, change="changed"))
        current_changed = True
    return found


def changed_definitions(files: Iterable[FileDiff]) -> list[Definition]:
    """Definitions in non-test files that the diff adds or whose body it changes."""
    result: list[Definition] = []
    seen: set[tuple[str, str]] = set()
    for file in files:
        if is_test_path(file.path):
            continue
        for hunk in file.hunks:
            for definition in _hunk_definitions(file.path, hunk):
                key = (definition.path, definition.name)
                if not _skip(definition.name) and key not in seen:
                    seen.add(key)
                    result.append(definition)
    return result


def untested_definitions(files: Iterable[FileDiff]) -> tuple[Definition, ...]:
    """Changed definitions that no test file in this diff mentions by name.

    Not proof of missing tests (they may live in files the PR does not touch), which is why
    the test reviewer receives this as a hint and still judges triviality and confidence.
    """
    files = list(files)
    test_text = "\n".join(
        line.content
        for file in files
        if is_test_path(file.path)
        for hunk in file.hunks
        for line in hunk.lines
        if line.kind != "removed"
    )
    untested = [
        d
        for d in changed_definitions(files)
        if re.search(rf"(?<![\w$]){re.escape(d.name)}(?![\w$])", test_text) is None
    ]
    return tuple(untested[:MAX_DEFINITIONS])
