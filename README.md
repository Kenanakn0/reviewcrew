# ReviewCrew

A multi-agent pull request review bot that runs as a GitHub App. Specialist agents
(security, performance, tests) review a PR's diff in parallel; their findings are
aggregated, verified against the diff and posted back as a single review.

> 🚧 Work in progress. Full documentation (architecture, GitHub App setup, evaluation
> results) will land as the project matures.

## Development

Requires [uv](https://docs.astral.sh/uv/). uv installs the pinned Python version (3.12)
automatically. To receive real webhooks you also need a GitHub App; see
[docs/github-app-setup.md](docs/github-app-setup.md).

```bash
uv sync                      # create .venv and install dependencies
cp .env.example .env         # local configuration (never commit .env)

docker run -d -p 6379:6379 redis:8.10-alpine   # the review queue
uv run reviewcrew            # API on http://127.0.0.1:8000 (receives webhooks)
uv run reviewcrew-worker     # worker (performs the reviews)
curl http://127.0.0.1:8000/health

uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy                  # type-check (strict)
uv run pytest                # tests (LLM and GitHub are mocked)
uv run pytest -m live        # optional: agents against the real LLM (costs money)
```

Per-repository settings: [docs/configuration.md](docs/configuration.md).

## License

MIT (to be added).
