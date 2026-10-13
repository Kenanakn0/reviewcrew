# syntax=docker/dockerfile:1

# ---- build: resolve dependencies and install the project into /app/.venv -------------------
FROM python:3.12-slim-trixie AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Dependencies first, so editing the source does not invalidate this layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-editable

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

# ---- runtime: only the virtual environment, run as an unprivileged user --------------------
FROM python:3.12-slim-trixie

RUN groupadd --system --gid 10001 reviewcrew \
    && useradd --system --uid 10001 --gid reviewcrew --no-create-home --shell /usr/sbin/nologin reviewcrew

COPY --from=builder --chown=reviewcrew:reviewcrew /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production

WORKDIR /app
USER reviewcrew

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

# The API; docker-compose.yml runs the worker from the same image with `reviewcrew-worker`.
CMD ["uvicorn", "reviewcrew.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
