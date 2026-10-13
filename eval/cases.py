"""Evaluation cases: a small change to a repository plus the findings a reviewer should make.

Layout of one case directory:

    eval/cases/<name>/
        case.yml        title, optional description, expected findings
        before/<path>   files as they were (omit for new files)
        after/<path>    files after the change (omit for deleted files)

`case.yml`:

    title: Add user search
    expected:                        # empty list = a clean case (measures false positives)
      - category: security           # security | performance | tests
        path: app/users.py
        line_contains: 'f"SELECT'    # first line in after/ containing this text
        span: 2                      # optional: number of lines the issue covers
        note: SQL injection via f-string
    scored: [security, performance]  # optional: categories this case is scored on (default:
                                     # all). Lets a security case ignore debatable
                                     # "no tests for this" remarks. Clean cases score all.

Expected lines are located by content rather than number, so editing a case cannot leave a
stale line number behind, and nothing in the code hints at the answer.
"""

import difflib
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from reviewcrew.agents.models import AgentName

CASES_DIR = Path(__file__).parent / "cases"


class ExpectedSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: AgentName
    path: str
    line_contains: str = Field(min_length=1)
    span: int = Field(default=1, ge=1)
    note: str = ""


ALL_CATEGORIES: tuple[AgentName, ...] = ("security", "performance", "tests")


class CaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    description: str = ""
    expected: tuple[ExpectedSpec, ...] = ()
    scored: tuple[AgentName, ...] = ALL_CATEGORIES


class ExpectedFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: AgentName
    path: str
    start: int  # new-file line numbers, inclusive
    end: int
    note: str = ""


class EvalCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    title: str
    expected: tuple[ExpectedFinding, ...]
    scored: tuple[AgentName, ...]
    diff: str
    head_contents: dict[str, str]  # after/ files, used for surrounding context

    @property
    def is_clean(self) -> bool:
        return not self.expected


class CaseError(ValueError):
    pass


def _read_tree(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def build_diff(before: dict[str, str], after: dict[str, str], *, context: int = 3) -> str:
    """A git-style unified diff (`diff --git` headers) from two file trees."""
    parts: list[str] = []
    for path in sorted(before.keys() | after.keys()):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        old_lines = (old or "").splitlines(keepends=True)
        new_lines = (new or "").splitlines(keepends=True)
        header = [f"diff --git a/{path} b/{path}\n"]
        if old is None:
            header.append("new file mode 100644\n")
        elif new is None:
            header.append("deleted file mode 100644\n")
        body = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile="/dev/null" if old is None else f"a/{path}",
                tofile="/dev/null" if new is None else f"b/{path}",
                n=context,
            )
        )
        for index, line in enumerate(body):
            if not line.endswith("\n"):  # last line of a file without a trailing newline
                body[index] = line + "\n\\ No newline at end of file\n"
        parts.append("".join(header + body))
    return "".join(parts)


def _locate(spec: ExpectedSpec, after: dict[str, str], case: str) -> ExpectedFinding:
    content = after.get(spec.path)
    if content is None:
        raise CaseError(f"{case}: expected finding in {spec.path}, which is not in after/")
    for number, line in enumerate(content.splitlines(), start=1):
        if spec.line_contains in line:
            return ExpectedFinding(
                category=spec.category,
                path=spec.path,
                start=number,
                end=number + spec.span - 1,
                note=spec.note,
            )
    raise CaseError(f"{case}: no line in {spec.path} contains {spec.line_contains!r}")


def load_case(directory: Path) -> EvalCase:
    spec = CaseSpec.model_validate(
        yaml.safe_load((directory / "case.yml").read_text(encoding="utf-8"))
    )
    before = _read_tree(directory / "before")
    after = _read_tree(directory / "after")
    diff = build_diff(before, after)
    if not diff:
        raise CaseError(f"{directory.name}: before/ and after/ are identical")
    unscored = {e.category for e in spec.expected} - set(spec.scored)
    if unscored:
        raise CaseError(f"{directory.name}: expected categories not scored: {sorted(unscored)}")
    if not spec.expected and set(spec.scored) != set(ALL_CATEGORIES):
        raise CaseError(f"{directory.name}: clean cases are scored on every category")
    return EvalCase(
        name=directory.name,
        title=spec.title,
        expected=tuple(_locate(e, after, directory.name) for e in spec.expected),
        scored=spec.scored,
        diff=diff,
        head_contents=after,
    )


def load_cases(root: Path = CASES_DIR, *, only: set[str] | None = None) -> list[EvalCase]:
    directories = sorted(p for p in root.iterdir() if (p / "case.yml").is_file())
    if only:
        directories = [d for d in directories if d.name in only]
    return [load_case(directory) for directory in directories]
