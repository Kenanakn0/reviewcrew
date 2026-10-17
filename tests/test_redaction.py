import base64

import pytest

from eval.cases import build_diff
from reviewcrew.diff.parser import parse_diff
from reviewcrew.diff.processor import process_diff
from reviewcrew.redaction import (
    MASK,
    find_secrets,
    is_known_token,
    mask,
    redact,
    secrets_in_diff,
)
from reviewcrew.rules.secrets import scan_secrets
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


# --- GitHub's stateless installation tokens: ghs_<app id>_<JWT>, about 520 characters ---------


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


# A fake token in the new shape. The payload and signature bytes are chosen so that their
# base64url text contains both "-" and "_", as real JWT segments can.
STATELESS = "ghs_1234567_" + ".".join(
    [
        _b64url(b'{"alg":"RS256","typ":"JWT"}'),
        _b64url(bytes(range(200)) + b"\xfb\xff" * 10),
        _b64url(b"\xfe\xff\xfb" * 45),
    ]
)


def test_the_fake_stateless_token_has_the_new_shape() -> None:
    assert 500 <= len(STATELESS) <= 600
    jwt_part = STATELESS.removeprefix("ghs_1234567_")
    assert jwt_part.count(".") == 2
    assert "-" in jwt_part
    assert "_" in jwt_part


def test_stateless_token_is_found_whole() -> None:
    assert STATELESS in find_secrets(f'token = client.installation_token()  # "{STATELESS}"')
    assert is_known_token(STATELESS)


@pytest.mark.parametrize("ending", [".", ". Rotate it.", ".\n", "),", '"'])
def test_punctuation_after_the_token_is_not_part_of_it(ending: str) -> None:
    text = f"The bot printed {STATELESS}{ending}"

    found = find_secrets(text)
    redacted = redact(text, set())

    assert STATELESS in found
    # The generic JWT pattern also matches the inner JWT; nothing may reach past the token.
    assert all(value in STATELESS for value in found)
    assert STATELESS[4:] not in redacted
    assert redacted == f"The bot printed {mask(STATELESS)}{ending}"


def test_classic_tokens_still_match_and_keep_a_final_period() -> None:
    classic = "ghs_" + "A1b2C3d4" * 4 + "Zz9Y"

    assert find_secrets(f"leaked {classic}.") == {classic}


@pytest.mark.parametrize(
    "line",
    [
        "def ghs_token_from_environment():",
        "ghp_settings_loader_module = load()",
    ],
)
def test_snake_case_names_with_a_token_prefix_are_not_tokens(line: str) -> None:
    assert find_secrets(line) == set()


def test_secret_scan_reports_a_hardcoded_stateless_token() -> None:
    files = parse_diff(build_diff({}, {"app/gh.py": f'client = Github("{STATELESS}")\n'}))

    (finding,) = scan_secrets(files)

    assert finding.line == 1
    assert "known API token" in finding.explanation
    assert STATELESS not in finding.model_dump_json()
