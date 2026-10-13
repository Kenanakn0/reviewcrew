# Contributing

Thanks for your interest! Issues and pull requests are welcome.

## Setup

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

All four must pass; CI runs the same commands. The tests mock GitHub, the LLM and Redis, so
no credentials are needed.

## Guidelines

- **Tests with every change.** New behaviour comes with tests in the same pull request.
  Agent behaviour that depends on the model is better covered by an evaluation case
  (`eval/cases/`, see `eval/cases.py`) than by a unit test.
- **Types.** `mypy --strict` is enforced; data crossing a boundary (webhooks, LLM output,
  configuration) is a Pydantic model.
- **Security.** Never commit secrets (`.env` and `*.pem` are ignored). Treat anything from
  a pull request as untrusted: it must not be executed, must stay inside the prompt's data
  markers, and must not reach logs or comments unfiltered.
- **Commits** follow [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, ...).
- **Prompts** live in `src/reviewcrew/agents/prompts/`. When you change one, run the
  evaluation (`uv run python -m eval.run`) before and after and mention the difference in
  the pull request.
