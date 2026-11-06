# Backend handbook — edge, MQTT, API, ingest, Postgres

## Run it

| Command | What |
|---|---|
| `make dev` | install the uv workspace (Python 3.12) — run first in every new worktree |
| `make up` / `make down` | Mosquitto :1883, Postgres+pgvector :5433, MediaMTX :8554/:8889, ingest ×2, api :8000 |
| `make api` | API on the host with reload (reads `.env`) |
| `make edge SOURCE=http://<phone>:8080/video` | real edge (needs `models/`, run from the repo root) |
| `make fake-edge SCENARIO=unattended SPEED=10` | scripted scenario through the real pipeline (unattended, hand, queue, uncleared) |
| `make test` / `make test-all` / `make lint` | unit / + integration (Docker) / ruff + mypy |
| `make schema` | regenerate JSON Schema from contracts |
| `make eval` | Romanian request → rule eval (20 cases, real API calls) |
| `make keys` / `make telegram-id` | paste API keys into `.env` / detect the Telegram group |
| `make vapid` | generate the Web Push VAPID keys into `.env` (never printed; kept if already set) |

`.env` holds every secret (names in `.env.example`); never print or commit values.
Models: `uv run python tools/download_models.py` → `models/` (gitignored).

## Services

| Service | Code | Role |
|---|---|---|
| edge | `apps/edge` | camera → YOLO11n + ByteTrack → pose (table zones) → behaviour + CLIP → role → situation engine → blurred snapshot → MQTT |
| ingest ×2 | `apps/ingest` | shared subscription → Postgres → Telegram + Web Push notifiers (composite) |
| api | `apps/api` | REST + WS for the dashboard; publishes retained edge state; Claude translator; staff enrolment |
| mosquitto | `infra/mosquitto` | auth from `.env`, per-device ACL |
| postgres | `infra/postgres` | Postgres 17 + pgvector, Alembic migrations (`migrate` service) |
| mediamtx | `infra/mediamtx` | RTSP in → WebRTC/WHEP out for the dashboard |

## MQTT topics (always via `aivee_contracts.topics.Topics`)

Root `aivee/<site>/<device>/…`

| Leaf | Direction | QoS / retain | Payload |
|---|---|---|---|
| `status` | edge → | 1, retained, LWT `offline` | DeviceStatus |
| `events` | edge → | 1 | AlertEvent (opened/closed) |
| `metrics` | edge → | 0 | Metrics (every 5 s) |
| `suggestions` | edge → | 1 | StaffSuggestion |
| `snapshots/<id>` | edge → | 1 | blurred JPEG bytes |
| `rules` | → edge | 1, retained | RuleSet (complete) |
| `config` | → edge | 1, retained | DeviceConfig: cameras + zones (complete) |
| `profiles` | → edge | 1, retained | StaffProfiles (complete) |
| `commands`, `detections` | → edge / edge → | 1 / 0 | *in progress (edge-commands PR)* |

Ingest uses `$share/ingest/aivee/+/+/events` and `.../suggestions`. ACL: each edge user writes only its own
device topics (`%u`), so `DEVICE` must equal `MQTT_EDGE_USER` (`edge-01`).

## Edge pipeline facts
- INT8 OpenVINO on the i7-1355U: ~20 FPS detection, ~12 FPS with pose; phone stream 8–11 FPS in practice.
- Engine `grace_s=1.5`; tracks forgotten after 5 s; role hysteresis 0.7 / 0.4; behaviour 0.5 + appearance 0.5.
- Appearance is off by default (`--appearance`), ~0.6 s per crop, at most once per 2 s per person.
- Live alert time is wall clock.

## Request → rule
`apps/api/.../rules/translator.py`: `messages.parse`, model `claude-opus-5-5`, effort low, `RuleDraft` output;
fixed instructions first, camera zones last (cache-friendly). Handles refusal / max_tokens / SDK errors with
Romanian messages. Eval: `evals/nl_to_rule` — 20/20, median 2.4 s.

## Known gaps
- `POST /api/cameras` with an existing id overwrites it (no 409) and ignores a `device` field.
- Snapshot dir differs between host API (`./snapshots`) and the ingest volume.
- Fake edge zone ids (`masa-1`) don't follow retained config ids.
- Edge commands (confirm/reject staff), suggestion snapshots, live detections and `ROTATE` — in progress.
