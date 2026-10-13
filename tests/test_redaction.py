import pytest

from reviewcrew.diff.processor import process_diff
from reviewcrew.redaction import MASK, find_secrets, mask, redact, secrets_in_diff
from tests.helpers import load_diff

KEY = "pk9f3Kq7Zr2LmX8vBn4TdW1yHs6Gc0Ea"  # the fake key in vulnerable.diff


@pytest.mark.parametrize(
    ("line", "secret"),
    [
        ('PAYMENTS_API_KEY = "pk9f3Kq7Zr2LmX8vBn4TdW1yHs6Gc0Ea"', KEY),
        ("password: 'hunter2hunter2'", "hunter2hunter2"),
        ('config["auth_token"] = "abc123def456ghi"', "abc123def456ghi"),
        ("aws = AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
        (
            "t = 'ghp_abcdefghijklmnopqrstuvwxyz0123456789'",
            "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        ),
        ("DB = 'postgres://admin:s3cr3tpw@db:5432/app'", "s3cr3tpw"),
    ],
)
def test_find_secrets(line: str, secret: str) -> None:
    assert secret in find_secrets(line)


@pytest.mark.parametrize(
    "line",
    [
        'api_key = os.environ["API_KEY"]',
        "token = get_token()",
        'name = "a perfectly normal string"',
        "password_field = forms.CharField()",
    ],
)
def test_ordinary_code_is_not_a_secret(line: str) -> None:
    assert find_secrets(line) == set()


def test_secrets_are_taken_from_added_lines_of_the_diff() -> None:
    diff = process_diff(load_diff("vulnerable.diff"))

    assert secrets_in_diff(diff.files.values()) == {KEY}


def test_mask_keeps_a_short_prefix_only() -> None:
    assert mask(KEY) == f"pk9f…{MASK}"
    assert mask("short-pw") == MASK


def test_redact_replaces_every_occurrence() -> None:
    text = f"Key {KEY} is hardcoded; rotate {KEY}."

    redacted = redact(text, {KEY})

    assert KEY not in redacted
    assert redacted.count(MASK) == 2


def test_redact_catches_known_token_formats_even_if_not_listed() -> None:
    assert "AKIAIOSFODNN7EXAMPLE" not in redact("found AKIAIOSFODNN7EXAMPLE", set())
