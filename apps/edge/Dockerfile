# AiVee vision worker: the edge pipeline in a container. Build from the repo root:
#   docker build -f apps/edge/Dockerfile -t aivee-edge:dev .
#
# Cloud mode: compose profile `cloud` runs it next to MediaMTX and reads the stream the
# restaurant's connector pushes (SOURCE=rtsp://mediamtx:8554/<camera-id>).
# Edge box / customer PC: the same image, with SOURCE pointing at the local camera.
# Models are mounted read-only at /app/models (download them with tools/download_models.py).
# Frames are processed in memory only; nothing is written to disk.
FROM ghcr.io/astral-sh/uv:0.8.5 AS uv

FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

# OpenCV (pulled in by ultralytics) and OpenVINO/torch need these shared libraries.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Workspace metadata first so the dependency layer is cached across code changes.
COPY pyproject.toml uv.lock ./
COPY packages/contracts/pyproject.toml packages/contracts/
COPY apps/edge/pyproject.toml apps/edge/
COPY apps/api/pyproject.toml apps/api/
COPY apps/ingest/pyproject.toml apps/ingest/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package aivee-edge --no-install-workspace

COPY packages/contracts packages/contracts
COPY apps/edge apps/edge
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package aivee-edge

# Ultralytics writes its settings under $HOME; give the user a home it owns.
RUN useradd --system --uid 10001 --create-home aivee
USER aivee
ENV YOLO_CONFIG_DIR=/home/aivee/.config/Ultralytics

CMD ["python", "-m", "aivee_edge"]
