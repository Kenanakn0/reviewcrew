import pytest

from eval.cases import build_diff
from reviewcrew.diff.definitions import (
    MAX_DEFINITIONS,
    changed_definitions,
    definition_name,
    is_test_path,
    untested_definitions,
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
        "@@ -5,4 +5,4 @@ def total(items):\n"
        "     n = 0\n"
        "     n = 0\n"
        "     n = 0\n"
        "-    return sum(items)\n"
        "+    return sum(items) * 2\n"
    )

    (definition,) = changed_definitions(parse_diff(diff))

    # Anchored at the change itself, a line GitHub can comment on.
    assert (definition.name, definition.change, definition.line) == ("total", "changed", 8)


def test_change_below_a_visible_header_points_at_the_header() -> None:
    before = "def total(items):\n    return sum(items)\n"
    after = "def total(items):\n    return sum(items) * 2\n"

    (definition,) = changed_definitions(files({"app/cart.py": before}, {"app/cart.py": after}))

    assert (definition.name, definition.line) == ("total", 1)


def test_dunders_tests_and_test_files_are_skipped() -> None:
    code = (
        "class A:\n    def __init__(self):\n        pass\n\n    def test_x(self):\n        pass\n"
    )
    found = changed_definitions(files({}, {"app/a.py": code, "tests/test_a.py": "def helper():\n"}))

    assert [d.name for d in found] == ["A"]


def test_functions_mentioned_by_a_test_file_in_the_pr_are_not_untested() -> None:
    code = LOGIN + "\n\ndef logout(session):\n    session.clear()\n"
    test = "from app.auth import login\n\ndef test_login():\n    assert login(db, 'a', 'b')\n"

    untested = untested_definitions(files({}, {"app/auth.py": code, "tests/test_auth.py": test}))

    assert [d.name for d in untested] == ["logout"]


def test_name_matching_is_whole_word() -> None:
    test = "def test_x():\n    assert login_admin()\n"

    untested = untested_definitions(files({}, {"app/auth.py": LOGIN, "tests/test_x.py": test}))

    assert [d.name for d in untested] == ["login"]


def test_untested_list_is_capped() -> None:
    code = "".join(f"def f{i}():\n    return {i}\n\n" for i in range(MAX_DEFINITIONS + 5))

    assert len(untested_definitions(files({}, {"app/many.py": code}))) == MAX_DEFINITIONS
