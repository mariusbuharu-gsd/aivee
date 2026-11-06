# AiVee HTTP API. Build from the repo root: docker build -f apps/api/Dockerfile .
# UV_EXTRAS="--extra ml" adds the enrolment models (CPU torch; image ~2.6 GB unpacked,
# ~0.8 GB compressed); without it the image is slim and POST /api/staff/photos answers 503
# with a Romanian message while everything else works. Compose: API_UV_EXTRAS in .env.
FROM ghcr.io/astral-sh/uv:0.8.5 AS uv

FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
ARG UV_EXTRAS=""

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

# OpenCV (enrolment) needs these shared libraries even in its headless build.
RUN if [ -n "$UV_EXTRAS" ]; then \
      apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
      && rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/contracts/pyproject.toml packages/contracts/
COPY apps/edge/pyproject.toml apps/edge/
COPY apps/api/pyproject.toml apps/api/
COPY apps/ingest/pyproject.toml apps/ingest/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package aivee-api $UV_EXTRAS --no-install-workspace

COPY packages/contracts packages/contracts
COPY apps/edge apps/edge
COPY apps/api apps/api
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package aivee-api $UV_EXTRAS

# The HF cache dir must exist (owned by aivee) before compose mounts the `hf-cache` volume
# there, or the volume is created root-owned and CLIP weights cannot be downloaded.
RUN useradd --system --uid 10001 --create-home aivee \
    && mkdir -p /data/snapshots /home/aivee/.cache/huggingface \
    && chown aivee /data/snapshots && chown -R aivee /home/aivee/.cache
USER aivee
ENV SNAPSHOT_DIR=/data/snapshots
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["uvicorn", "aivee_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
