.PHONY: dev test test-all lint fmt up down schema keys telegram-id vapid api eval
dev:
	uv sync --all-packages
test:
	uv run pytest
test-all:
	uv run pytest -m "integration or not integration"
lint:
	uv run ruff check . && uv run ruff format --check . && uv run mypy
fmt:
	uv run ruff check --fix . && uv run ruff format .
up:
	docker compose up -d
down:
	docker compose down
schema:
	uv run python -m aivee_contracts.export
keys:
	./tools/setup-keys.sh
telegram-id:
	uv run python tools/telegram_chat_id.py
vapid:
	uv run python tools/gen_vapid.py
api:
	uv run uvicorn aivee_api.main:app --reload --port 8000 --env-file .env
eval:
	uv run --env-file .env python evals/nl_to_rule/run.py

.PHONY: edge fake-edge
SOURCE ?= 0
SCENARIO ?= unattended
SPEED ?= 10
edge:
	uv run python -m aivee_edge --source $(SOURCE)
fake-edge:
	uv run python tools/fake_edge.py --scenario $(SCENARIO) --speed $(SPEED)

.PHONY: data-dirs
# Create bind-mounted dirs as the current user before `make up` (Docker would create them as root).
data-dirs:
	mkdir -p data/snapshots recordings

.PHONY: record
# Backup demo clip: make record SOURCE=http://PHONE:8080/video SECONDS=60 ROTATE=90 NAME=sala-1
# Replay (already upright): make edge SOURCE=recordings/sala-1.mp4
SECONDS ?= 30
ROTATE ?= 0
NAME ?= clip
record:
	uv run python tools/record_clip.py --source $(SOURCE) --seconds $(SECONDS) --rotate $(ROTATE) --out recordings/$(NAME).mp4

.PHONY: seed
# Demo org, location `demo` and owner@/manager@/staff@aivee.demo (idempotent). The password is
# DEMO_PASSWORD from .env; when empty, one is generated into .env (never printed).
seed:
	uv run --env-file .env python -m aivee_api.accounts.seed --env-file .env
