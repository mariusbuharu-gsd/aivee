.PHONY: dev test test-all lint fmt up down schema keys telegram-id
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

.PHONY: edge fake-edge
SOURCE ?= 0
SCENARIO ?= unattended
SPEED ?= 10
edge:
	uv run python -m aivee_edge --source $(SOURCE)
fake-edge:
	uv run python tools/fake_edge.py --scenario $(SCENARIO) --speed $(SPEED)
