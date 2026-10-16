from eval.cases import build_diff
from reviewcrew.diff.parser import parse_diff
from reviewcrew.rules.secrets import TITLE, scan_secrets

PASSWORD = "demo_pass_2024!"  # noqa: S105 - test fixture, not a real secret
STRIPE = "sk_live_51HxTestFakeKey9f8a7b6c5d"  # format of a known token, fake value


def test_hardcoded_password_is_reported_on_its_exact_line() -> None:
    code = f'import sqlite3\n\nDB_PASSWORD = "{PASSWORD}"\n\n\ndef login():\n    pass\n'

    (finding,) = scan_secrets(parse_diff(build_diff({}, {"app/auth.py": code})))

    assert (finding.agent, finding.source, finding.path, finding.line) == (
        "security",
        "rule",
        "app/auth.py",
        3,
    )
    assert finding.title == TITLE
    assert finding.severity == "high"
    assert "credential-like name" in finding.explanation


def test_the_value_never_appears_in_the_finding() -> None:
    code = f'TOKEN = "{STRIPE}"\nDB_PASSWORD = "{PASSWORD}"\n'

    findings = scan_secrets(parse_diff(build_diff({}, {"app/settings.py": code})))

    assert [f.line for f in findings] == [1, 2]
    for finding in findings:
        dumped = finding.model_dump_json()
        assert STRIPE not in dumped
        assert PASSWORD not in dumped


def test_known_token_formats_are_more_confident() -> None:
    code = f'client = Stripe("{STRIPE}")\nPASSWORD = "{PASSWORD}"\n'

    token, password = scan_secrets(parse_diff(build_diff({}, {"app/pay.py": code})))

    assert "known API token" in token.explanation
    assert token.confidence > password.confidence


def test_only_added_lines_are_scanned() -> None:
    before = f'PASSWORD = "{PASSWORD}"\nTIMEOUT = 5\n'
    after = f'PASSWORD = "{PASSWORD}"\nTIMEOUT = 10\n'

    assert scan_secrets(parse_diff(build_diff({"a.py": before}, {"a.py": after}))) == ()


def test_code_without_secrets_has_no_findings() -> None:
    code = 'import os\n\nPASSWORD = os.environ["DB_PASSWORD"]\nNAME = "reviewcrew"\n'

    assert scan_secrets(parse_diff(build_diff({}, {"app/config.py": code}))) == ()
