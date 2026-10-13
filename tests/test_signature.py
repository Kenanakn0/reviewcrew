import hashlib
import hmac

import pytest

from reviewcrew.webhook.signature import compute_signature, verify_signature

SECRET = b"It's a Secret to Everybody"
BODY = b"Hello, World!"


def test_compute_signature_matches_github_documented_example() -> None:
    # Example from GitHub's "Validating webhook deliveries" documentation.
    expected = "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"

    assert compute_signature(SECRET, BODY) == expected


def test_valid_signature_is_accepted() -> None:
    header = "sha256=" + hmac.new(SECRET, BODY, hashlib.sha256).hexdigest()

    assert verify_signature(SECRET, BODY, header)


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "sha256=",
        "sha256=deadbeef",
        "sha1=" + hmac.new(SECRET, BODY, hashlib.sha1).hexdigest(),
        hmac.new(SECRET, BODY, hashlib.sha256).hexdigest(),  # missing prefix
    ],
)
def test_malformed_or_wrong_signatures_are_rejected(header: str | None) -> None:
    assert not verify_signature(SECRET, BODY, header)


def test_signature_from_another_secret_is_rejected() -> None:
    assert not verify_signature(SECRET, BODY, compute_signature(b"other secret", BODY))


def test_tampered_body_is_rejected() -> None:
    header = compute_signature(SECRET, BODY)

    assert not verify_signature(SECRET, BODY + b" ", header)
