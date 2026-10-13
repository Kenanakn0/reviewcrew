"""Path globs for `ignore:` in `.reviewcrew.yml`.

Semantics (close to .gitignore):

- `*` matches within one path segment, `?` one character of a segment, `[abc]` a class.
- `**` matches any number of segments: `docs/**`, `**/fixtures/*.json`, `src/**/gen_*.py`.
- A pattern without a `/` matches the file name in any directory: `*.snap`, `CHANGELOG.md`.
- A trailing `/` means "everything under this directory": `vendor/` == `vendor/**`.
"""

import re
from functools import lru_cache


@lru_cache(maxsize=512)
def compile_glob(pattern: str) -> re.Pattern[str]:
    pattern = pattern.strip().lstrip("/")
    if pattern.endswith("/"):
        pattern += "**"
    if "/" not in pattern:
        pattern = "**/" + pattern

    regex = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            regex.append("(?:[^/]+/)*")  # zero or more whole segments
            i += 3
        elif pattern.startswith("**", i):
            regex.append(".*")
            i += 2
        elif pattern[i] == "*":
            regex.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            regex.append("[^/]")
            i += 1
        elif pattern[i] == "[":
            end = pattern.find("]", i + 1)
            if end == -1:
                regex.append(re.escape("["))
                i += 1
            else:
                body = pattern[i + 1 : end].replace("\\", "\\\\")
                if body.startswith("!"):
                    body = "^" + body[1:]
                regex.append(f"[{body}]")
                i = end + 1
        else:
            regex.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(regex) + r"\Z")


def matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    return any(compile_glob(pattern).match(path) for pattern in patterns)
