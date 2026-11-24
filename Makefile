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

.PHONY: edge-box edge-cameras
# The edge box: connect as MQTT_EDGE_USER and run the cameras added in the dashboard for this
# device (Camere → Caută camere), starting and stopping them as they change. Also answers the
# dashboard's camera discovery and camera test. SOURCE and CAMERAS must not be set in .env:
# they are dev overrides and win. See docs/handbook/ip-cameras.md.
edge-box:
	uv run python -m aivee_edge
# Same command. With CAMERAS in .env (dev override) it runs exactly those cameras instead:
#   CAMERAS=cam-01=rtsp://USER:PASS@IP1:554/stream2;cam-02=rtsp://USER:PASS@IP2:554/stream2
edge-cameras:
	uv run python -m aivee_edge

.PHONY: camera-check
# Open each camera for ~8 s: resolution, fps, first-frame latency, codec (passwords masked).
#   make camera-check                       # every camera in CAMERAS (.env)
#   make camera-check URLS="cam-01=rtsp://…" CHECK_SECONDS=10
URLS ?=
camera-check:
	uv run python tools/camera_check.py --seconds $(or $(CHECK_SECONDS),8) $(URLS)

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

.PHONY: eval-vision record-cams
# Vision eval on labelled real-camera clips (evals/vision/README.md). Green on zero clips.
CLIPS ?= recordings/eval
eval-vision:
	uv run python evals/vision/run.py --clips $(CLIPS)
# Record all cameras at once into recordings/eval/<name>-<time>.mp4, for labelling and INT8
# calibration. Keep camera URLs (they carry credentials) in env vars, never in this file:
#   make record-cams CAMS="cam-01=$CAM_01_URL cam-02=$CAM_02_URL" SECONDS=600
REC_FPS ?= 15
record-cams:
	@test -n "$(CAMS)" || { echo 'record-cams: set CAMS="cam-01=<url> cam-02=<url>"' >&2; exit 1; }
	@mkdir -p recordings/eval; stamp=$$(date +%Y%m%d-%H%M); pids=""; \
	for pair in $(CAMS); do \
	  name=$${pair%%=*}; url=$${pair#*=}; \
	  uv run python tools/record_clip.py --source "$$url" --seconds $(SECONDS) --fps $(REC_FPS) \
	    --out recordings/eval/$$name-$$stamp.mp4 & pids="$$pids $$!"; \
	done; status=0; for p in $$pids; do wait $$p || status=1; done; exit $$status
