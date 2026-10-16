"""Report hardcoded secrets on added lines without an LLM.

Uses the same detector that masks secrets in the bot's comments, so anything the review
would redact is also reported, on the exact line. The value itself never appears in the
finding.
"""

from collections.abc import Iterable

from reviewcrew.agents.models import Finding
from reviewcrew.diff.models import FileDiff
from reviewcrew.redaction import find_secrets, is_known_token

TITLE = "Hardcoded secret"
SUGGESTION = (
    "Load the value from an environment variable or a secrets manager instead, and rotate "
    "it: it stays readable in the git history."
)


def scan_secrets(files: Iterable[FileDiff]) -> tuple[Finding, ...]:
    findings = []
    for file in files:
        for hunk in file.hunks:
            for line in hunk.lines:
                if line.kind != "added" or line.new_lineno is None:
                    continue
                values = find_secrets(line.content)
                if not values:
                    continue
                known = any(is_known_token(value) for value in values)
                what = (
                    "a value in the format of a known API token"
                    if known
                    else "a string literal assigned to a credential-like name"
                )
                findings.append(
                    Finding(
                        agent="security",
                        source="rule",
                        path=file.path,
                        line=line.new_lineno,
                        severity="high",
                        confidence=0.95 if known else 0.85,
                        title=TITLE,
                        explanation=(
                            f"This line adds {what}. Anyone who can read the repository or "
                            "its history can use the credential."
                        ),
                        suggestion=SUGGESTION,
                    )
                )
    return tuple(findings)
