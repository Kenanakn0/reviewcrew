"""Find the functions and classes a diff adds or meaningfully changes, and which of them the
pull request's test files mention. Regex based and language-agnostic enough for a hint: the
test reviewer gets these facts instead of having to work them out (small models often don't).
"""

import re
from collections.abc import Iterable
from typing import Literal, NamedTuple

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
_IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")
MAX_DEFINITIONS = 30  # listed in one hint; more would crowd the prompt
# A body edit counts as a change worth testing from this many changed lines on (blank lines
# and pure renames excluded): a one-line tweak is not "new logic".
MIN_CHANGED_LINES = 2


class Definition(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    name: str
    line: int  # the header line, or the first changed line when the header is not shown
    change: Literal["added", "changed"]


class CoverageHints(BaseModel):
    """What the diff says about tests, for the test reviewer."""

    model_config = ConfigDict(frozen=True)

    test_paths: tuple[str, ...] = ()  # test files the pull request adds or changes
    untested: tuple[Definition, ...] = ()  # no test file in the PR mentions these
    covered: tuple[Definition, ...] = ()  # a test file in the PR mentions these


class _Edit(NamedTuple):
    name: str
    anchor: int
    kind: Literal["added", "removed"]
    content: str


def is_test_path(path: str) -> bool:
    return _TEST_PATH.search(path) is not None


def definition_name(text: str) -> str | None:
    for pattern in _DEFINITIONS:
        if (match := pattern.match(text)) is not None:
            return match.group("name")
    return None


def _tracked_name(text: str) -> str | None:
    """Definition name, except dunder methods: their edits count for the enclosing class."""
    name = definition_name(text)
    return None if name is not None and name.startswith("__") and name.endswith("__") else name


def _hunk_changes(path: str, hunk: DiffHunk) -> tuple[list[Definition], list[_Edit]]:
    """Definitions whose header the hunk adds, and the body edits of the others."""
    headers: list[Definition] = []
    edits: list[_Edit] = []
    removed_names = {
        name
        for line in hunk.lines
        if line.kind == "removed" and (name := _tracked_name(line.content)) is not None
    }
    # Hunk headers often name the enclosing definition ("@@ ... @@ def handler(request):").
    current = _tracked_name(hunk.section)
    current_line: int | None = None
    current_is_new = False
    next_new = hunk.new_start  # new-file position of the next line, also for removed ones
    for line in hunk.lines:
        position = line.new_lineno or next_new
        if line.new_lineno is not None:
            next_new = line.new_lineno + 1
        name = _tracked_name(line.content)
        if line.kind == "removed" and name is not None:
            continue  # an old header; the added one, if any, decides what changed
        if name is not None:
            current, current_line = name, position
            # A rewritten signature (old header removed in the same hunk) is a change.
            current_is_new = line.kind == "added" and name not in removed_names
            if current_is_new:
                headers.append(Definition(path=path, name=name, line=position, change="added"))
            elif line.kind == "added":
                headers.append(Definition(path=path, name=name, line=position, change="changed"))
            continue
        if line.kind == "context" or current is None or current_is_new:
            continue
        if not line.content.strip():
            continue  # blank lines are layout, not logic
        kind: Literal["added", "removed"] = "added" if line.kind == "added" else "removed"
        edits.append(_Edit(current, current_line or position, kind, line.content))
    return headers, edits


def _shape(line: str) -> str:
    return " ".join(_IDENTIFIER.sub("x", line).split())


def _is_meaningful(edits: list[_Edit]) -> bool:
    added = [e.content for e in edits if e.kind == "added"]
    removed = [e.content for e in edits if e.kind == "removed"]
    if max(len(added), len(removed)) < MIN_CHANGED_LINES:
        return False
    # Same lines with only identifiers swapped: a rename, not new behaviour.
    return sorted(map(_shape, added)) != sorted(map(_shape, removed))


def changed_definitions(files: Iterable[FileDiff]) -> list[Definition]:
    """Definitions in non-test files that the diff adds or whose body it meaningfully changes."""
    result: list[Definition] = []
    for file in files:
        if is_test_path(file.path):
            continue
        headers: list[Definition] = []
        edits: dict[str, list[_Edit]] = {}
        for hunk in file.hunks:
            hunk_headers, hunk_edits = _hunk_changes(file.path, hunk)
            headers += hunk_headers
            for edit in hunk_edits:
                edits.setdefault(edit.name, []).append(edit)
        seen: set[str] = set()
        for definition in headers:
            if definition.name not in seen:
                seen.add(definition.name)
                result.append(definition)
        for name, body in edits.items():
            if name not in seen and _is_meaningful(body):
                seen.add(name)
                result.append(
                    Definition(path=file.path, name=name, line=body[0].anchor, change="changed")
                )
    return [d for d in result if not d.name.lower().startswith("test")]  # tests aren't logic


def coverage_hints(files: Iterable[FileDiff]) -> CoverageHints:
    """Split the changed definitions by whether a test file in this diff mentions them.

    "Untested" is not proof (tests may live in files the PR does not touch), which is why
    the test reviewer receives this as a hint and still judges triviality and confidence.
    """
    files = list(files)
    tests = [file for file in files if is_test_path(file.path)]
    test_text = "\n".join(
        line.content
        for file in tests
        for hunk in file.hunks
        for line in hunk.lines
        if line.kind != "removed"
    )
    untested: list[Definition] = []
    covered: list[Definition] = []
    for definition in changed_definitions(files):
        mentioned = re.search(rf"(?<![\w$]){re.escape(definition.name)}(?![\w$])", test_text)
        (covered if mentioned else untested).append(definition)
    return CoverageHints(
        test_paths=tuple(file.path for file in tests),
        untested=tuple(untested[:MAX_DEFINITIONS]),
        covered=tuple(covered[:MAX_DEFINITIONS]),
    )
