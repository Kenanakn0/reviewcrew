"""Verification of GitHub's `X-Hub-Signature-256` webhook header."""

import hashlib
import hmac

SIGNATURE_PREFIX = "sha256="


def compute_signature(secret: bytes, body: bytes) -> str:
    """Return the header value GitHub would send for `body` signed with `secret`."""
    digest = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def verify_signature(secret: bytes, body: bytes, signature_header: str | None) -> bool:
    """Check `signature_header` against the HMAC-SHA256 of the raw request body.

    The comparison is constant-time so the expected signature cannot be recovered
    by timing the response.
    """
    if not signature_header or not signature_header.startswith(SIGNATURE_PREFIX):
        return False
    expected = compute_signature(secret, body)
    return hmac.compare_digest(expected.encode(), signature_header.encode())
