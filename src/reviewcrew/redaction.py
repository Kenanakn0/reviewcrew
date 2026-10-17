"""Keep secret values out of the bot's own comments.

The agents are told never to repeat secrets, but a model can still quote a line verbatim.
Before publishing, every candidate secret found in the PR's added lines is masked in all
comment text.
"""

import re
from collections.abc import Iterable

from reviewcrew.diff.models import FileDiff

VISIBLE_PREFIX = 4
MASK = "[REDACTED]"

_TOKEN_PATTERNS = [
    re.compile(p)
    for p in (
        r"AKIA[0-9A-Z]{16}",  # AWS access key ID
        # GitHub, classic and stateless (`ghs_<app id>_<JWT>`). Requiring a digit keeps names
        # like `ghs_token_from_env` out; a final period is not part of the token.
        r"(?:ghp|gho|ghs|ghu|ghr)_(?=[A-Za-z0-9_\-]*[0-9])[A-Za-z0-9_\-]{20,}"
        r"(?:\.[A-Za-z0-9_\-]+)*",
        r"github_pat_[A-Za-z0-9_]{20,}",
        r"sk-ant-[A-Za-z0-9_\-]{20,}",  # Anthropic
        r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}",  # OpenAI-style
        r"(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}",  # Stripe
        r"xox[abprs]-[A-Za-z0-9\-]{10,}",  # Slack
        r"AIza[0-9A-Za-z_\-]{35}",  # Google API key
        r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",  # JWT
    )
]
# `name = "value"` where the name suggests a credential.
_ASSIGNMENT = re.compile(
    r"""(?ix)
    (?:key|secret|token|passw(?:or)?d|pwd|credential|auth|api[_-]?key|private)[a-z0-9_\-]*
    ["'\]]*\s*[:=]\s*(?:[a-z]+\()?\s*
    (?P<quote>["'])(?P<value>[^"'\s]{8,})(?P=quote)
    """
)
# Credentials embedded in URLs: scheme://user:password@host
_URL_CREDENTIALS = re.compile(r"[a-z][a-z0-9+.\-]*://[^/\s:@]+:(?P<value>[^@\s/]{6,})@", re.I)


def find_secrets(text: str) -> set[str]:
    """Return substrings of `text` that look like secret values."""
    found = {m.group(0) for pattern in _TOKEN_PATTERNS for m in pattern.finditer(text)}
    found.update(m.group("value") for m in _ASSIGNMENT.finditer(text))
    found.update(m.group("value") for m in _URL_CREDENTIALS.finditer(text))
    return found


def is_known_token(value: str) -> bool:
    """True when `value` has the format of a well-known credential (AWS, GitHub, Stripe…)."""
    return any(pattern.fullmatch(value) for pattern in _TOKEN_PATTERNS)


def secrets_in_diff(files: Iterable[FileDiff]) -> set[str]:
    """Candidate secrets on the lines a PR adds (removed lines are already public history)."""
    added = "\n".join(
        line.content
        for file in files
        for hunk in file.hunks
        for line in hunk.lines
        if line.kind == "added"
    )
    return find_secrets(added)


def mask(value: str) -> str:
    if len(value) < 12:
        return MASK
    return f"{value[:VISIBLE_PREFIX]}…{MASK}"


def redact(text: str, secrets: Iterable[str]) -> str:
    # Longest first, so a secret containing another one is masked as a whole.
    for value in sorted(set(secrets), key=len, reverse=True):
        text = text.replace(value, mask(value))
    # Catch well-known token formats even if they were not on an added line.
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub(lambda m: mask(m.group(0)), text)
    return text
