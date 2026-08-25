# syntax=docker/dockerfile:1.7
# Ask India API. Build from the repository root:
#   docker build -f apps/api/Dockerfile -t ghcr.io/astrohimanshu/ask-india-api:dev .
FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /app

FROM base AS builder
# Dependency layer first: only lock and manifests, so code changes do not reinstall packages.
COPY pyproject.toml uv.lock .python-version ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY packages/agents/pyproject.toml packages/agents/pyproject.toml
COPY packages/ingestion/pyproject.toml packages/ingestion/pyproject.toml
COPY packages/evals/pyproject.toml packages/evals/pyproject.toml
COPY packages/training/pyproject.toml packages/training/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages --no-install-workspace
COPY apps/api apps/api
COPY packages packages
COPY scripts scripts
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --all-packages
# Bake the embedding model so a cold container never downloads at request time.
ENV FASTEMBED_CACHE_PATH=/app/.fastembed
RUN /app/.venv/bin/python -c "from askindia_agents.embedder import FastEmbedEmbedder; FastEmbedEmbedder().embed(['warm up'])"

FROM base AS runtime
RUN useradd --create-home --uid 10001 askindia
COPY --from=builder --chown=askindia:askindia /app /app
USER askindia
ENV PATH="/app/.venv/bin:$PATH" FASTEMBED_CACHE_PATH=/app/.fastembed PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD curl -sf http://localhost:${PORT}/health || exit 1
CMD ["sh", "-c", "uvicorn askindia_api.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
