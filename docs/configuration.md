# Repository configuration (`.reviewcrew.yml`)

Place an optional `.reviewcrew.yml` at the repository root. Every key is optional.

```yaml
# Reviewers to run (default: all three).
agents: [security, performance, tests]

# Hide findings below this severity: low | medium | high | critical (default: low).
min_severity: medium

# Extra paths to skip, on top of the built-in filters (lock files, minified and
# generated files, binaries, vendored code).
ignore:
  - "docs/**"            # everything under docs/
  - "*.snap"             # a name without "/" matches in any directory
  - "**/fixtures/*.json" # ** spans any number of directories
  - "legacy/"            # trailing "/" = the whole directory

# Inline comments per pull request, 0-50 (default: the server's setting). Findings
# beyond the limit are listed in the summary comment.
max_comments: 15

# Language of the review text: en | tr (default: the server's setting).
language: en
```

## How it is applied

- The file is read from the pull request's **base** commit, not from the PR itself, so a
  pull request cannot switch off the reviewers that would flag it. Changes to
  `.reviewcrew.yml` take effect once merged.
- If the file is invalid (bad YAML, an unknown key or value), the review still runs with
  the default settings and the summary comment lists what is wrong.
- Cost and safety limits stay with the server operator and cannot be changed here: the
  per-PR token budget, timeouts and the confidence threshold.

## Server settings

Operators configure defaults and limits through environment variables; see `.env.example`.
The most relevant ones:

| Variable | Default | Meaning |
|---|---|---|
| `REVIEW_AGENTS` | all three | Default reviewers (JSON list) |
| `REVIEW_MIN_CONFIDENCE` | `0.5` | Findings below this confidence are hidden |
| `REVIEW_MAX_INLINE_COMMENTS` | `20` | Default inline comment limit |
| `REVIEW_TOKEN_BUDGET` | `300000` | Tokens one PR may spend; later chunks are skipped and reported |
| `REVIEW_DEDUP_TTL_SECONDS` | 7 days | How long a reviewed commit is remembered |
