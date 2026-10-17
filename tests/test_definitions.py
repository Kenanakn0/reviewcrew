import pytest

from eval.cases import build_diff
from reviewcrew.diff.definitions import (
    MAX_DEFINITIONS,
    changed_definitions,
    coverage_hints,
    definition_name,
    is_test_path,
)
from reviewcrew.diff.models import FileDiff
from reviewcrew.diff.parser import parse_diff


def files(before: dict[str, str], after: dict[str, str]) -> list[FileDiff]:
    return parse_diff(build_diff(before, after))


LOGIN = (
    "import sqlite3\n"
    "\n"
    "\n"
    "def login(conn, username, password):\n"
    "    cur = conn.cursor()\n"
    "    return cur.fetchone() is not None\n"
)


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_auth.py",
        "app/tests/helpers.py",
        "test_auth.py",
        "pkg/auth_test.go",
        "web/__tests__/login.js",
        "web/login.test.ts",
        "web/login.spec.js",
        "src/test/java/AuthTest.java",
        "AuthTests.cs",
    ],
)
def test_test_paths(path: str) -> None:
    assert is_test_path(path)


@pytest.mark.parametrize(
    "path", ["app/auth.py", "app/contest.py", "latest/notes.md", "web/attestation.ts"]
)
def test_non_test_paths(path: str) -> None:
    assert not is_test_path(path)


@pytest.mark.parametrize(
    ("line", "name"),
    [
        ("def login(conn, username):", "login"),
        ("    async def fetch(self) -> None:", "fetch"),
        ("class RateLimiter:", "RateLimiter"),
        ("export async function loadComments(id) {", "loadComments"),
        ("function* walk(tree) {", "walk"),
        ("export const total = (items) => items.length;", "total"),
        ("const handler = async event => {", "handler"),
        ("func (s *Server) Serve(addr string) error {", "Serve"),
        ("func main() {", "main"),
    ],
)
def test_definition_names(line: str, name: str) -> None:
    assert definition_name(line) == name


@pytest.mark.parametrize(
    "line", ["return login(conn)", "# def commented():", "x = lambda y: y", "const n = 3;"]
)
def test_lines_that_are_not_definitions(line: str) -> None:
    assert definition_name(line) is None


def test_added_function_is_listed_at_its_header() -> None:
    (definition,) = changed_definitions(files({}, {"app/auth.py": LOGIN}))

    assert (definition.path, definition.name, definition.line, definition.change) == (
        "app/auth.py",
        "login",
        4,
        "added",
    )


def test_changed_body_is_attributed_to_the_function_named_in_the_hunk_header() -> None:
    # The `def` is above the shown context; git names it after the second `@@`.
    diff = (
        "diff --git a/app/cart.py b/app/cart.py\n"
        "--- a/app/cart.py\n"
        "+++ b/app/cart.py\n"
        "@@ -5,4 +5,6 @@ def total(items):\n"
        "     n = 0\n"
        "     n = 0\n"
        "     n = 0\n"
        "-    return sum(items)\n"
        "+    if not items:\n"
        "+        raise ValueError('empty cart')\n"
        "+    return sum(items) * 2\n"
    )

    (definition,) = changed_definitions(parse_diff(diff))

    # Anchored at the change itself, a line GitHub can comment on.
    assert (definition.name, definition.change, definition.line) == ("total", "changed", 8)


TOTAL = "def total(items):\n    n = len(items)\n    return sum(items) / n\n"


def test_change_below_a_visible_header_points_at_the_header() -> None:
    after = "def total(items):\n    n = len(items) or 1\n    return round(sum(items) / n, 2)\n"

    (definition,) = changed_definitions(files({"app/cart.py": TOTAL}, {"app/cart.py": after}))

    assert (definition.name, definition.line, definition.change) == ("total", 1, "changed")


@pytest.mark.parametrize(
    "after",
    [
        "def total(items):\n    n = len(items)\n    return sum(items) / n * 2\n",
        "def total(items):\n    count = len(items)\n    return sum(items) / count\n",
        "def total(items):\n    n = len(items)\n\n\n    return sum(items) / n\n",
    ],
    ids=["one-line", "rename", "blank-lines"],
)
def test_small_or_cosmetic_body_edits_are_not_listed(after: str) -> None:
    assert changed_definitions(files({"app/cart.py": TOTAL}, {"app/cart.py": after})) == []


def test_blank_lines_after_a_function_do_not_change_it() -> None:
    before = "def subtotal(prices):\n    return sum(prices)\n"
    after = before + "\n\ndef apply_discount(total, code):\n    return total\n"

    found = changed_definitions(files({"app/pricing.py": before}, {"app/pricing.py": after}))

    assert [(d.name, d.change) for d in found] == [("apply_discount", "added")]


def test_rewritten_signature_is_a_change_not_an_addition() -> None:
    before = "def area(w):\n    return w * w\n"
    after = "def area(w, h):\n    return w * h\n"

    (definition,) = changed_definitions(files({"app/geo.py": before}, {"app/geo.py": after}))

    assert (definition.name, definition.change) == ("area", "changed")


def test_dunder_edits_count_for_the_enclosing_class() -> None:
    before = "class RateLimiter:\n    def __init__(self, limit):\n        self.limit = limit\n"
    after = (
        "class RateLimiter:\n"
        "    def __init__(self, limit, burst=0):\n"
        "        self.limit = limit + burst\n"
    )

    (definition,) = changed_definitions(files({"app/rl.py": before}, {"app/rl.py": after}))

    assert (definition.name, definition.change, definition.line) == ("RateLimiter", "changed", 1)


def test_tests_and_test_files_are_skipped() -> None:
    code = (
        "class A:\n    def __init__(self):\n        pass\n\n    def test_x(self):\n        pass\n"
    )
    found = changed_definitions(files({}, {"app/a.py": code, "tests/test_a.py": "def helper():\n"}))

    assert [d.name for d in found] == ["A"]


def test_coverage_splits_by_mention_in_the_prs_test_files() -> None:
    code = LOGIN + "\n\ndef logout(session):\n    session.clear()\n"
    test = "from app.auth import login\n\ndef test_login():\n    assert login(db, 'a', 'b')\n"

    hints = coverage_hints(files({}, {"app/auth.py": code, "tests/test_auth.py": test}))

    assert [d.name for d in hints.untested] == ["logout"]
    assert [d.name for d in hints.covered] == ["login"]
    assert hints.test_paths == ("tests/test_auth.py",)


def test_name_matching_is_whole_word() -> None:
    test = "def test_x():\n    assert login_admin()\n"

    hints = coverage_hints(files({}, {"app/auth.py": LOGIN, "tests/test_x.py": test}))

    assert [d.name for d in hints.untested] == ["login"]
    assert hints.covered == ()


def test_lists_are_capped() -> None:
    code = "".join(f"def f{i}():\n    return {i}\n\n" for i in range(MAX_DEFINITIONS + 5))

    assert len(coverage_hints(files({}, {"app/many.py": code})).untested) == MAX_DEFINITIONS
