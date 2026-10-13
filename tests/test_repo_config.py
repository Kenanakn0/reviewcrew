import pytest

from reviewcrew.pipeline.options import ReviewOptions
from reviewcrew.repo_config.globs import compile_glob, matches_any
from reviewcrew.repo_config.schema import MAX_CONFIG_BYTES, RepoConfig, parse_config

# --- globs -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "path"),
    [
        ("docs/**", "docs/index.md"),
        ("docs/**", "docs/a/b/c.md"),
        ("docs/", "docs/a/b.md"),
        ("**/fixtures/*.json", "tests/fixtures/a.json"),
        ("**/fixtures/*.json", "fixtures/a.json"),
        ("src/**/gen_*.py", "src/gen_x.py"),
        ("src/**/gen_*.py", "src/a/b/gen_x.py"),
        ("*.snap", "ui/__snapshots__/button.snap"),
        ("CHANGELOG.md", "CHANGELOG.md"),
        ("CHANGELOG.md", "packages/core/CHANGELOG.md"),
        ("/README.md", "README.md"),
        ("file?.txt", "file1.txt"),
        ("[ab].py", "a.py"),
        ("[!ab].py", "c.py"),
    ],
)
def test_glob_matches(pattern: str, path: str) -> None:
    assert compile_glob(pattern).match(path)


@pytest.mark.parametrize(
    ("pattern", "path"),
    [
        ("docs/**", "src/docs/index.md"),  # anchored at the root
        ("docs/*", "docs/a/b.md"),  # * stays within one segment
        ("*.py", "app.pyc"),
        ("src/*.py", "src/a/b.py"),
        ("file?.txt", "file10.txt"),
        ("[ab].py", "c.py"),
        ("a.b", "axb"),  # dots are literal
    ],
)
def test_glob_does_not_match(pattern: str, path: str) -> None:
    assert not compile_glob(pattern).match(path)


def test_matches_any() -> None:
    assert matches_any("docs/x.md", ("*.py", "docs/**"))
    assert not matches_any("src/x.ts", ("*.py", "docs/**"))
    assert not matches_any("src/x.ts", ())


# --- schema ----------------------------------------------------------------------------------

VALID = """
agents: [security, tests, security]
min_severity: medium
ignore:
  - "docs/**"
  - "*.snap"
max_comments: 10
language: tr
"""


def test_valid_config() -> None:
    loaded = parse_config(VALID)

    assert loaded.source == "file"
    assert loaded.errors == ()
    assert loaded.config == RepoConfig(
        agents=("security", "tests"),  # duplicates removed, order kept
        min_severity="medium",
        ignore=("docs/**", "*.snap"),
        max_comments=10,
        language="tr",
    )


def test_missing_file_means_defaults() -> None:
    loaded = parse_config(None)

    assert (loaded.source, loaded.errors, loaded.config) == ("defaults", (), RepoConfig())


def test_empty_file_is_valid() -> None:
    loaded = parse_config("# nothing configured yet\n")

    assert (loaded.source, loaded.errors) == ("file", ())


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("agents: [security, linter]", "`agents.1`"),
        ("agents: []", "`agents`"),
        ("min_severity: urgent", "`min_severity`"),
        ("max_comments: 500", "`max_comments`"),
        ("max_comments: -1", "`max_comments`"),
        ("language: de", "`language`"),
        ("ignore: ['']", "`ignore`"),
        ("unknown_option: true", "`unknown_option`"),
        ("- just\n- a list", "top level must be a mapping"),
        ("agents: [security\n", "invalid YAML (line 2)"),
    ],
)
def test_invalid_configs_report_the_problem_and_fall_back(text: str, expected: str) -> None:
    loaded = parse_config(text)

    assert loaded.source == "defaults"
    assert loaded.config == RepoConfig()
    assert any(expected in error for error in loaded.errors), loaded.errors


def test_errors_do_not_echo_values() -> None:
    loaded = parse_config("language: s3cr3t-value-from-config")

    assert "s3cr3t" not in " ".join(loaded.errors)


def test_oversized_file_is_rejected() -> None:
    loaded = parse_config("ignore:\n" + "  - 'x'\n" * (MAX_CONFIG_BYTES // 8 + 1))

    assert loaded.errors == ("file is larger than 64 KB",)


# --- applying it -----------------------------------------------------------------------------


def test_repo_config_refines_server_defaults() -> None:
    defaults = ReviewOptions(language="en", max_inline_comments=20, token_budget=1000)

    options = defaults.with_repo_config(parse_config(VALID).config)

    assert options.agents == ("security", "tests")
    assert options.language == "tr"
    assert options.max_inline_comments == 10
    assert options.aggregation.min_severity == "medium"
    assert options.diff.filters.ignore_globs == ("docs/**", "*.snap")
    # Server-controlled limits are untouched.
    assert options.token_budget == 1000
    assert options.aggregation.min_confidence == defaults.aggregation.min_confidence


def test_empty_repo_config_keeps_defaults() -> None:
    defaults = ReviewOptions(agents=("security",), language="tr", max_inline_comments=7)

    assert defaults.with_repo_config(RepoConfig()) == defaults.model_copy(
        update={"aggregation": defaults.aggregation}
    )
