# Ingest worker (also runs DB migrations: `python -m aivee_api.db.migrate upgrade`).
# Build from the repo root: docker build -f apps/ingest/Dockerfile .
FROM ghcr.io/astral-sh/uv:0.8.5 AS uv

FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app
# Workspace metadata first so the dependency layer is cached across code changes.
COPY pyproject.toml uv.lock ./
COPY packages/contracts/pyproject.toml packages/contracts/
COPY apps/edge/pyproject.toml apps/edge/
COPY apps/api/pyproject.toml apps/api/
COPY apps/ingest/pyproject.toml apps/ingest/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package aivee-ingest --no-install-workspace

COPY packages/contracts packages/contracts
COPY apps/api apps/api
COPY apps/ingest apps/ingest
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package aivee-ingest

RUN useradd --system --uid 10001 aivee \
    && mkdir -p /data/snapshots && chown aivee /data/snapshots
USER aivee
ENV SNAPSHOT_DIR=/data/snapshots

CMD ["python", "-m", "aivee_ingest"]
