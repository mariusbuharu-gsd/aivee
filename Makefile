.PHONY: dev test test-all lint fmt up down schema keys telegram-id vapid api eval e2e
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
e2e:
	cd apps/dashboard && npm run e2e
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

.PHONY: edge-usb
# Phone camera over USB (stable where venue Wi-Fi stalls the MJPEG stream). Needs USB debugging allowed
# and IP Webcam started (FPS limit 15, quality 50). TARGET_FPS=30 stays above the 15 fps source so the
# frame pacing keeps every frame.
USB_PORT ?= 28080
ADB ?= $(shell command -v adb 2>/dev/null || echo $(HOME)/.local/bin/adb)
edge-usb:
	@$(ADB) devices | grep -q '	device$$' || { echo "edge-usb: no authorised adb device. Plug the phone in, enable USB debugging and accept 'Allow USB debugging'." >&2; exit 1; }
	$(ADB) forward tcp:$(USB_PORT) tcp:8080
	ROTATE=90 APPEARANCE=true TARGET_FPS=30 uv run python -m aivee_edge --source http://localhost:$(USB_PORT)/video

.PHONY: data-dirs
# Create bind-mounted dirs as the current user before `make up` (Docker would create them as root).
data-dirs:
	mkdir -p data/snapshots data/videos recordings

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

.PHONY: connector cloud-up cloud-down
# Cloud mode. Restaurant side: push one camera to the AiVee cloud (no analysis on site).
#   make connector SOURCE=http://PHONE:8080/video CAMERA_ID=cam-01 ROTATE=90
# Cloud side: run the vision worker for CAMERA_ID next to MediaMTX.
CAMERA_ID ?= cam-01
connector:
	uv run --env-file .env python apps/connector/connector.py --source $(SOURCE) --camera-id $(CAMERA_ID) --rotate $(ROTATE)
cloud-up:
	docker compose --profile cloud up -d --build vision
cloud-down:
	docker compose --profile cloud stop vision
