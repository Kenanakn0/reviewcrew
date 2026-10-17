# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-10-17

First release.

### Added

- **GitHub App webhook API** (FastAPI): HMAC-SHA256 signature check with a constant-time
  comparison, `pull_request` events `opened`, `synchronize`, `reopened` and
  `ready_for_review` only, draft PRs skipped, `/health` endpoint.
- **GitHub App authentication**: App JWT and cached installation tokens, refreshed before
  they expire.
- **Diff processing** with `unidiff`: new-file line mapping, filters for lock, minified,
  generated, binary, deleted and oversized files, token-bounded chunks with surrounding
  context.
- **Three review agents** running in parallel (security, performance, tests) with
  provider-agnostic structured output for the Anthropic API and any OpenAI-compatible
  endpoint; a local Ollama model is the default. Tolerant parsing of common small-model
  output slips, one retry on invalid output.
- **Pipeline**: per-agent timeouts and failure isolation, a per-PR token budget,
  de-duplication across agents, confidence and severity thresholds, anchoring to lines
  GitHub accepts, a single `COMMENT` review with inline comments and a summary table.
- **Deterministic checks next to the LLM**: a rule-based secret scan that reports
  hardcoded credentials on their exact line; every LLM finding carries a category and the
  performance and test agents' findings outside their area are dropped in code; the test
  agent is told which changed functions the PR's tests do or do not mention.
- **Observability**: raw findings per agent and every merge are logged with secret values
  masked; the summary shows raw versus shown counts and dropped findings.
- **Per-repository configuration** with `.reviewcrew.yml`, read from the base commit and
  validated; problems are reported in the summary.
- **Queue and idempotency**: Redis + `arq` worker, the webhook answers `202` at once, each
  `(repo, PR, head SHA)` is reviewed once, transient GitHub errors are retried.
- **Evaluation**: 26 tuning cases and 8 held-out cases, precision, recall and F1 per agent,
  the secret scan scored separately, `--repeat N` for mean and range over several runs.
- **Packaging**: multi-stage Docker image running as a non-root user, Compose stack with
  the API, the worker and Redis; the API is published on loopback only and Redis not at all.
- Documentation: README, GitHub App setup with smee.io, local LLM guide, configuration
  reference, MIT license, contributing guide.

### Security

- Pull request content is passed to the models as data between random per-request markers;
  the bot never approves or requests changes.
- Secret values on added lines are masked in every comment the bot writes, including
  GitHub's stateless installation tokens (`ghs_<app id>_<JWT>`, about 520 characters).
- The GitHub App needs only *Pull requests* (read & write), *Contents* (read) and
  *Metadata* (read).

[1.0.0]: https://github.com/Kenanakn0/reviewcrew/releases/tag/v1.0.0
