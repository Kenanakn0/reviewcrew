# ReviewCrew

A multi-agent pull request review bot that runs as a GitHub App. Specialist agents
(security, performance, tests) review a PR's diff in parallel; their findings are
aggregated, verified against the diff and posted back as a single review.

> 🚧 Work in progress. Full documentation (architecture, GitHub App setup, evaluation
> results) will land as the project matures.

## Development

Requires [uv](https://docs.astral.sh/uv/). uv installs the pinned Python version (3.12)
automatically.

```bash
uv sync                      # create .venv and install dependencies
cp .env.example .env         # local configuration (never commit .env)

uv run reviewcrew            # start the API on http://127.0.0.1:8000
curl http://127.0.0.1:8000/health

uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy                  # type-check (strict)
uv run pytest                # tests
```

## License

MIT (to be added).
