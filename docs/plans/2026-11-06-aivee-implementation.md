# AiVee MVP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> Commits in this repo carry **no AI attribution** (no Co-Authored-By, no session links, no "Claude Code").

**Goal:** A working hospitality demo in 24 h: a phone camera watches "tables", AiVee learns who is staff,
and alerts staff on Telegram/PWA when a table is unattended, a guest raises a hand, a queue forms, or a
table is left uncleared, with rules written in Romanian.

**Architecture:** Edge process (YOLO + ByteTrack + role scoring + situation engine, CPU/OpenVINO)
publishes over MQTT (Mosquitto with ACL, LWT, retained, QoS 1, shared subscriptions) to an ingest worker
that stores in Postgres + pgvector; a FastAPI API serves the dashboard/PWA and turns Romanian requests
into rules via Claude. Pure domain code sits behind `Protocol` ports; adapters wrap YOLO, CLIP, MQTT,
Postgres, Telegram and Claude.

**Tech Stack:** Python 3.12 (uv workspace), Pydantic v2, ultralytics (YOLO11, pose, ByteTrack),
open_clip, paho-mqtt v2 (edge) / aiomqtt (ingest, api), FastAPI, SQLAlchemy 2 async + asyncpg, Alembic,
pgvector, anthropic SDK (`claude-opus-5-5`, structured outputs), React + Vite + TS, Mosquitto 2,
Postgres 17 + pgvector, MediaMTX, pytest + testcontainers, ruff, mypy, GitHub Actions.

Design: `docs/plans/2026-11-06-aivee-design.md`.

---

## 0. Team, streams, sessions

| Stream | Owner | Folders | Claude sessions (each in its own git worktree) |
|---|---|---|---|
| **A — Vision & edge** | Vasi Dancu | `apps/edge/` | A1 detection/tracking/pose · A2 role (behaviour + appearance) |
| **B — Core & backend** | Marius | `packages/contracts/`, `apps/edge/src/aivee_edge/domain/`, `apps/api/`, `apps/ingest/`, `infra/`, CI | B1 contracts + situation engine · B2 api/ingest/MQTT · B3 tests/CI/review |
| **C — Product & pitch** | Radu Nedela | `apps/dashboard/`, `apps/site/`, `docs/`, slides | C1 dashboard + PWA · C2 site + docs + pitch |

Owners are a proposal; swap freely. Rules:
- `packages/contracts/` changes only through B.
- Merge to `main` only through PRs with green CI; B merges at checkpoints M1/M2/M3.
- Worktrees: `git worktree add ../aivee-<stream> -b feature/<stream>`.

Milestones: **M1 14:30**, **M2 18:30**, **M3 00:00 (feature freeze)**, **code freeze Sat 10:30**.

---

## Phase 0 — Scaffold (B, 10:50–11:40) → everyone unblocked

### Task 0.1: uv workspace and tooling

**Files:**
- Create: `pyproject.toml`, `.python-version`, `Makefile`, `CLAUDE.md`, `.pre-commit-config.yaml`
- Create: `packages/contracts/pyproject.toml`, `packages/contracts/src/aivee_contracts/__init__.py`
- Create: `apps/{edge,api,ingest}/pyproject.toml`, `apps/*/src/aivee_*/__init__.py`

**Step 1: root `pyproject.toml`**

```toml
[project]
name = "aivee"
version = "0.1.0"
requires-python = ">=3.12,<3.13"

[tool.uv]
package = false

[tool.uv.workspace]
members = ["packages/*", "apps/edge", "apps/api", "apps/ingest"]

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "pytest-cov>=5", "ruff>=0.7", "mypy>=1.13",
       "testcontainers[postgres]>=4.8", "pre-commit>=4"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "RUF"]

[tool.mypy]
strict = true
packages = ["aivee_contracts"]

[tool.pytest.ini_options]
markers = ["integration: needs Docker (testcontainers)"]
addopts = "-m 'not integration'"
asyncio_mode = "auto"
```

`.python-version`: `3.12`

**Step 2: member packages.** Each `apps/<x>/pyproject.toml`:

```toml
[project]
name = "aivee-edge"          # aivee-api, aivee-ingest
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = ["aivee-contracts"]

[tool.uv.sources]
aivee-contracts = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/aivee_edge"]
```

`packages/contracts/pyproject.toml`: same shape, `name = "aivee-contracts"`, `dependencies = ["pydantic>=2.9"]`.

**Step 3: `Makefile`**

```make
.PHONY: dev test test-all lint fmt up down schema
dev:      ; uv sync --all-packages
test:     ; uv run pytest
test-all: ; uv run pytest -m "integration or not integration"
lint:     ; uv run ruff check . && uv run ruff format --check . && uv run mypy
fmt:      ; uv run ruff check --fix . && uv run ruff format .
up:       ; docker compose up -d
down:     ; docker compose down
schema:   ; uv run python -m aivee_contracts.export
```

**Step 4: `CLAUDE.md`** (short; sessions read it first)

```markdown
# AiVee — rules for every session
- Read docs/plans/2026-11-06-aivee-design.md and this plan before coding.
- Stay inside your stream's folders. Never edit packages/contracts/ unless you are stream B.
- TDD: failing test → minimal code → green → commit. `make test` and `make lint` must pass.
- Domain code (apps/edge/src/aivee_edge/domain/) is pure: no IO, no imports of cv2/torch/mqtt.
- Secrets only in .env (never committed). Use .env.example for names.
- Commits: `type(scope): summary` + why-body. NO AI attribution lines. PR bodies: no AI footer.
- Code, comments, docs in English. UI copy in Romanian.
```

**Step 5: verify**

Run: `make dev && uv run python -c "import aivee_contracts, aivee_edge, aivee_api, aivee_ingest"`
Expected: no error.

**Step 6: commit** `chore: scaffold uv workspace, tooling and session rules`

### Task 0.2: infrastructure (compose)

**Files:**
- Create: `docker-compose.yml`, `infra/mosquitto/mosquitto.conf`, `infra/mosquitto/acl`,
  `infra/mosquitto/entrypoint.sh`, `infra/postgres/init.sql`, `infra/mediamtx/mediamtx.yml`

**`infra/mosquitto/mosquitto.conf`**

```conf
listener 1883
allow_anonymous false
password_file /mosquitto/config/passwd
acl_file /mosquitto/config/acl
persistence true
persistence_location /mosquitto/data/
```

**`infra/mosquitto/acl`**

```conf
user aivee-api
topic readwrite aivee/#

user aivee-ingest
topic read aivee/#

pattern write aivee/+/%u/status
pattern write aivee/+/%u/events
pattern write aivee/+/%u/metrics
pattern write aivee/+/%u/suggestions
pattern write aivee/+/%u/snapshots/#
pattern read  aivee/+/%u/rules
pattern read  aivee/+/%u/profiles
```

(`%u` = username, so edge user `edge-01` can only use `aivee/<site>/edge-01/...`.)

**`infra/mosquitto/entrypoint.sh`**: builds `passwd` from env at start, then runs mosquitto.

```sh
#!/bin/sh
set -e
f=/mosquitto/config/passwd
: > "$f"
mosquitto_passwd -b "$f" "$MQTT_API_USER" "$MQTT_API_PASSWORD"
mosquitto_passwd -b "$f" "$MQTT_INGEST_USER" "$MQTT_INGEST_PASSWORD"
mosquitto_passwd -b "$f" "$MQTT_EDGE_USER" "$MQTT_EDGE_PASSWORD"
chmod 0700 "$f"
exec mosquitto -c /mosquitto/config/mosquitto.conf
```

**`infra/postgres/init.sql`**: `CREATE EXTENSION IF NOT EXISTS vector;`

**`docker-compose.yml`**

```yaml
services:
  mosquitto:
    image: eclipse-mosquitto:2
    env_file: .env
    entrypoint: ["/bin/sh", "/entrypoint.sh"]
    volumes:
      - ./infra/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro
      - ./infra/mosquitto/acl:/mosquitto/config/acl:ro
      - ./infra/mosquitto/entrypoint.sh:/entrypoint.sh:ro
      - mosquitto-data:/mosquitto/data
    ports: ["1883:1883"]
  postgres:
    image: pgvector/pgvector:pg17
    env_file: .env
    volumes:
      - ./infra/postgres/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
      - pg-data:/var/lib/postgresql/data
    ports: ["5432:5432"]
    healthcheck: { test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER"], interval: 5s }
  mediamtx:
    image: bluenviron/mediamtx:latest
    volumes: ["./infra/mediamtx/mediamtx.yml:/mediamtx.yml:ro"]
    ports: ["8554:8554", "8889:8889"]
volumes: { mosquitto-data: {}, pg-data: {} }
```

(`api`, `ingest` ×2 and `dashboard` services are added in their tasks.)

**Verify:**
Run: `make up && docker compose exec mosquitto mosquitto_sub -u "$MQTT_API_USER" -P "$MQTT_API_PASSWORD" -t 'aivee/#' -W 2`
Expected: exits on timeout (auth ok). Run with a wrong password → `Connection Refused: not authorised`.

**Commit:** `chore(infra): add mosquitto with ACL, postgres with pgvector, mediamtx`

### Task 0.3: CI

**Files:** Create `.github/workflows/ci.yml`, `.github/pull_request_template.md`

```yaml
name: ci
on: { push: { branches: [main] }, pull_request: {} }
jobs:
  python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with: { enable-cache: true }
      - run: uv sync --all-packages
      - run: uv run ruff check . && uv run ruff format --check .
      - run: uv run mypy
      - run: uv run pytest -m "integration or not integration" --cov --cov-report=term
      - run: make schema && git diff --exit-code packages/contracts/schema apps/dashboard/src/contracts
  secrets:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: gitleaks/gitleaks-action@v2
        env: { GITHUB_TOKEN: "${{ secrets.GITHUB_TOKEN }}" }
```

(Dashboard job — `npm ci && npm run lint && npm run build` — is added in Task C1.)
PR template: checklist from the design's Definition of Done.

**Commit:** `ci: add lint, type, test, schema-drift and secret scan jobs`
Then: push, enable branch protection on `main` (require `python` + `secrets`).

---

## Phase 1 — Contracts (B, 11:40–12:30)

### Task 1.1: core models

**Files:**
- Create: `packages/contracts/src/aivee_contracts/{geometry,rules,events,topics,export}.py`
- Test: `packages/contracts/tests/test_contracts.py`

**Step 1: failing tests**

```python
import pytest
from pydantic import ValidationError
from aivee_contracts.geometry import Zone
from aivee_contracts.rules import Condition, Rule, Action
from aivee_contracts.topics import Topics

def test_zone_polygon_needs_three_points():
    with pytest.raises(ValidationError):
        Zone(id="t1", name="Masa 1", tag="table", polygon=[(0.1, 0.1), (0.2, 0.2)])

def test_zone_coordinates_are_normalised():
    with pytest.raises(ValidationError):
        Zone(id="t1", name="Masa 1", tag="table", polygon=[(0, 0), (1.5, 0), (0, 1)])

def test_unattended_table_rule_round_trips():
    rule = Rule(
        id="r1", camera_id="cam-1", name="Masă neservită", prompt_ro="...",
        zone_tag="table",
        all_of=[
            Condition(kind="present", role="guest", min_duration_s=60),
            Condition(kind="absent", role="staff", min_duration_s=600),
        ],
        action=Action(type="telegram"), cooldown_s=300,
    )
    assert Rule.model_validate_json(rule.model_dump_json()) == rule

def test_pose_condition_requires_pose():
    with pytest.raises(ValidationError):
        Condition(kind="pose", role="guest")

def test_topics_are_scoped_per_device():
    t = Topics(site="demo", device="edge-01")
    assert t.events == "aivee/demo/edge-01/events"
    assert t.snapshot("e1") == "aivee/demo/edge-01/snapshots/e1"
    assert Topics.shared_events() == "$share/ingest/aivee/+/+/events"
```

**Step 2:** `uv run pytest packages/contracts -v` → FAIL (`ModuleNotFoundError`).

**Step 3: implementation**

`geometry.py`

```python
from pydantic import BaseModel, Field, field_validator

Point = tuple[float, float]

class Zone(BaseModel):
    id: str
    name: str
    tag: str                      # "table", "entrance", "staff"
    polygon: list[Point] = Field(min_length=3)

    @field_validator("polygon")
    @classmethod
    def _normalised(cls, pts: list[Point]) -> list[Point]:
        if any(not (0 <= c <= 1) for p in pts for c in p):
            raise ValueError("coordinates must be normalised to [0, 1]")
        return pts
```

`rules.py`

```python
from typing import Literal, Self
from pydantic import BaseModel, Field, model_validator

Role = Literal["guest", "staff", "any"]

class Condition(BaseModel):
    kind: Literal["present", "absent", "count", "pose", "objects_unattended"]
    role: Role = "any"
    min_duration_s: int = Field(default=0, ge=0)
    min_count: int = Field(default=1, ge=1)
    pose: Literal["raised_hand"] | None = None
    objects: list[str] = Field(default_factory=list)   # COCO names: cup, bottle, bowl…

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.kind == "pose" and self.pose is None:
            raise ValueError("pose condition needs 'pose'")
        if self.kind == "objects_unattended" and not self.objects:
            raise ValueError("objects_unattended needs 'objects'")
        return self

class Action(BaseModel):
    type: Literal["telegram", "push", "webhook"]
    target: str | None = None

class Rule(BaseModel):
    id: str
    camera_id: str
    name: str
    prompt_ro: str
    zone_tag: str                 # evaluated once per zone with this tag
    all_of: list[Condition] = Field(min_length=1)
    action: Action
    cooldown_s: int = Field(default=300, ge=0)
    enabled: bool = True
```

`events.py`

```python
from datetime import datetime
from typing import Literal
from pydantic import BaseModel

class AlertEvent(BaseModel):
    event_id: str                 # UUID, idempotency key
    rule_id: str
    camera_id: str
    zone_id: str
    state: Literal["opened", "closed"]
    at: datetime
    summary_ro: str
    snapshot: bool = False

class DeviceStatus(BaseModel):
    device: str
    state: Literal["online", "offline"]
    version: str = "0.1.0"
    cameras: list[str] = []

class Metrics(BaseModel):
    device: str
    fps: float
    verified_ratio: float         # share of frames sent to the heavy model
    cpu_percent: float

class StaffSuggestion(BaseModel):
    suggestion_id: str
    camera_id: str
    track_id: int
    staff_score: float
    reason_ro: str                # "vizitează 5 mese, se mișcă 30 m/min"
```

`topics.py`

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Topics:
    site: str
    device: str

    def _t(self, leaf: str) -> str:
        return f"aivee/{self.site}/{self.device}/{leaf}"

    @property
    def status(self) -> str: return self._t("status")
    @property
    def events(self) -> str: return self._t("events")
    @property
    def metrics(self) -> str: return self._t("metrics")
    @property
    def suggestions(self) -> str: return self._t("suggestions")
    @property
    def rules(self) -> str: return self._t("rules")
    @property
    def profiles(self) -> str: return self._t("profiles")
    def snapshot(self, event_id: str) -> str: return self._t(f"snapshots/{event_id}")

    @staticmethod
    def shared_events() -> str: return "$share/ingest/aivee/+/+/events"
```

`export.py`: writes `model_json_schema()` for every model to `packages/contracts/schema/*.json`
(C later adds TS generation with `json-schema-to-typescript` into `apps/dashboard/src/contracts/`).

**Step 4:** `uv run pytest packages/contracts -v` → PASS; `make lint` → clean.

**Step 5: commit** `feat(contracts): add zones, rules, events and MQTT topics`

---

## Phase 2 — Situation engine (B, 12:30–14:00) — the core "own solution"

Pure code in `apps/edge/src/aivee_edge/domain/`. No cv2/torch/MQTT imports.

### Task 2.1: geometry

**Files:** `domain/geometry.py`, test `apps/edge/tests/domain/test_geometry.py`

Tests: point inside/outside a square; point on a concave polygon; `foot_point(bbox)` returns the
bottom-centre of a box (a seated/standing person "is" where the feet are).

```python
def point_in_polygon(p: Point, poly: list[Point]) -> bool:  # ray casting
    x, y = p
    inside = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside

def foot_point(bbox: tuple[float, float, float, float]) -> Point:
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2, y2)
```

Commit: `feat(edge): add zone geometry helpers`

### Task 2.2: observation model and zone state

**Files:** `domain/observation.py`, `domain/zone_state.py`, test `tests/domain/test_zone_state.py`

```python
@dataclass(frozen=True)
class TrackObs:
    track_id: int
    bbox: tuple[float, float, float, float]   # normalised
    role: Literal["guest", "staff"]
    raised_hand: bool = False

@dataclass(frozen=True)
class Frame:
    ts: float                                   # seconds, monotonic
    tracks: list[TrackObs]
    objects: list[tuple[str, tuple[float, float, float, float]]]  # (coco_name, bbox)
```

`ZoneState` keeps per zone: `occupied_since` (first guest present, reset when empty),
`last_seen[role]`, `objects_since`, `empty_since`. Rule: when a zone goes from no guest to guest,
`last_seen["staff"]` is reset to that moment — "nobody came **since they sat down**".

Tests (each a short simulated timeline):
- `test_present_duration_grows_while_guest_stays`
- `test_staff_absence_counts_from_when_guests_sat_down`
- `test_staff_visit_resets_absence`
- `test_zone_empty_resets_occupancy`
- `test_objects_without_people_tracks_duration`

Commit: `feat(edge): track per-zone presence, absence and objects over time`

### Task 2.3: condition evaluation and alert lifecycle

**Files:** `domain/engine.py`, test `tests/domain/test_engine.py`

`SituationEngine(rules, zones, clock)`:
- `step(frame) -> list[AlertEvent]` updates zone states, evaluates every enabled rule on every zone
  with `rule.zone_tag`, opens an alert when all conditions hold, closes it when they stop holding,
  and respects `cooldown_s` between openings for the same (rule, zone).
- `event_id` comes from an injected `id_factory` (deterministic in tests).

Tests mirror the four MVP events:
- `test_unattended_table_opens_after_threshold`
- `test_unattended_table_closes_when_staff_arrives`
- `test_raised_hand_opens_immediately`
- `test_queue_opens_at_min_count`
- `test_uncleared_table_needs_objects_and_no_people`
- `test_cooldown_blocks_reopen`
- `test_rule_applies_to_every_zone_with_tag` (two tables → two independent alerts)
- `test_disabled_rule_is_ignored`

Target: ≥ 90 % coverage on `domain/`. Commit: `feat(edge): add situation engine with alert lifecycle`

**→ M1 path:** B2 wires this to MQTT while A1 feeds real frames.

---

## Stream A — Vision & edge (Vasi, from 11:00)

Before 11:40 (while scaffold lands): phone stream works on the laptop
(`cv2.VideoCapture("http://<phone-ip>:8080/video")`), download `yolo11n.pt` and `yolo11n-pose.pt`,
export both with `model.export(format="openvino")`, measure FPS on CPU. Record 4 demo clips (one per event).

| Task | Files | Tests | Done when |
|---|---|---|---|
| **A1.1 Capture port** | `adapters/capture.py` (`FrameSource` protocol; `Cv2Source`, `FileSource`) | `test_file_source_yields_frames` (tiny mp4 fixture) | reads phone stream and files at fixed FPS |
| **A1.2 Detector + tracker** | `adapters/yolo.py` → `Detector` port returning persons + COCO objects with track ids (`model.track(persist=True, tracker="bytetrack.yaml")`) | `test_yolo_output_is_mapped_to_domain` with a fake result object | stable track ids on a demo clip, ≥ 8 FPS on CPU (OpenVINO) |
| **A1.3 Pose** | `adapters/pose.py`, `domain/pose.py` (`is_raised_hand(keypoints)`: wrist above shoulder + nose) | domain tests on keypoint fixtures (raised / not raised / missing) | runs only for tracks whose foot point is in a table zone |
| **A1.4 Edge loop** | `app.py`: source → detector → role → engine → publisher; `metrics.py` (fps, verified_ratio, cpu) | `test_pipeline_with_fakes` (all ports faked, asserts events published) | `uv run python -m aivee_edge --source clip.mp4` emits events |
| **A2.1 Behaviour features** | `domain/behaviour.py`: per track over a 180 s window → `speed_m_per_min` (normalised units), `zones_visited`, `stationary_ratio`, `in_staff_zone` | synthetic trajectories: walker vs sitter vs wandering guest | walker scores > 0.7, sitter < 0.2 |
| **A2.2 Appearance** | `adapters/clip_embedder.py` (open_clip ViT-B-32, crop → 512-d, L2-normalised); `domain/appearance.py` (cosine to profile centroids) | domain tests with hand-made vectors | crop embedded at most every 2 s per track |
| **A2.3 Role fusion** | `domain/role.py`: `staff_score = w_b·behaviour + w_a·appearance` (appearance weight 0 when no profile); hysteresis so roles don't flicker; emits `StaffSuggestion` when score > 0.7 and unconfirmed | fusion + hysteresis tests | suggestion appears within ~2 min of walking between tables |
| **A2.4 Face blur** | `adapters/blur.py` (OpenCV YuNet face detector → Gaussian blur) applied before any snapshot leaves the device | test on a fixture image: output differs inside face box | every published snapshot is blurred |
| **A2.5 (could) Moondream verify** | `adapters/verifier.py` via Ollama | fake-HTTP test | only on alert-open frames; `verified_ratio` shown |

---

## Stream B — Backend (Marius, after Phase 2)

| Task | Files | Tests | Done when |
|---|---|---|---|
| **B2.1 MQTT publisher (edge)** | `apps/edge/.../adapters/mqtt.py` (paho v2: LWT `offline` retained on `status`, `online` on connect, QoS 1, `clean_start=False`, subscribe `rules`/`profiles`) | integration: rule retained → received after reconnect | edge shows online/offline in DB |
| **B2.2 DB schema** | `apps/api/.../db/models.py`, Alembic migration 0001: `sites, devices, cameras, zones(jsonb), rules(jsonb, prompt_ro), events, snapshots, staff_profiles(vector(512)), staff_examples(vector(512)), suggestions` | migration up/down on testcontainer | `alembic upgrade head` clean |
| **B2.3 Ingest worker** | `apps/ingest/...`: aiomqtt, shared subscription `$share/ingest/aivee/+/+/events`, upsert by `event_id`, status → devices, snapshots → volume, then notify (Telegram) | integration: duplicate event stored once; LWT → offline; two workers split messages | M1 alert lands in Telegram |
| **B2.4 Telegram notifier** | `adapters/telegram.py` (httpx, `sendPhoto` with blurred snapshot, Romanian text) | fake HTTP test | message with photo in the group |
| **B2.5 API** | FastAPI by domain: `cameras/ zones/ rules/ events/ devices/ staff/` (router, schemas, service, repository); WebSocket `/ws/events`; publishing a rule = upsert + retained MQTT publish | httpx AsyncClient tests per router | dashboard can CRUD zones/rules |
| **B2.6 Request → rule (Claude)** | `rules/translator.py`: `RuleTranslator` port; `ClaudeRuleTranslator` with `client.messages.parse(model="claude-opus-5-5", output_format=RuleDraft, output_config={"effort": "low"})`; system prompt lists zones/tags and the 4 event patterns; handle refusal and validation errors | unit with fake client; `evals/nl_to_rule/` 20 Romanian prompts → expected rules, `make eval` prints X/20 | "Anunță ospătarul dacă…" → valid rule in < 5 s |
| **B2.7 Enrolment** | `staff/enrol.py`: upload photos (or a short video → frames every 0.5 s) → person crops → embeddings → centroid → retained `profiles` on MQTT; confirm suggestion → crops become examples | unit + pgvector nearest-profile integration test | uploaded T-shirt photo boosts staff_score live |
| **B3 Tests/CI/review** | `tests/integration/conftest.py` (Postgres via testcontainers, Mosquitto via `DockerContainer("eclipse-mosquitto:2")` with mounted config), `tools/fake_edge.py` (replays clips/events) | — | CI green, `/code-review` on every PR before merge |

---

## Stream C — Product & pitch (Radu, from 11:00)

Before 11:40: Vite + React + TS app in `apps/dashboard`, copy the look from the design canvas
(https://claude.ai/artifact/Nv1eJXZf2UUNqF5F1WKVFf), develop against `tools/fake_edge.py` / mocked API.

| Task | Files | Done when |
|---|---|---|
| **C1.1 Shell + live** | layout, cameras grid, WebRTC player from MediaMTX, device online/offline | live phone video in browser |
| **C1.2 Zone editor** | draw polygons on the frame, name + tag (table/entrance/staff), save via API | zones saved and visible on edge |
| **C1.3 Rule composer** | Romanian textarea + mic (Web Speech API), "Ce am înțeles" panel, JSON preview, activate | rule created from text |
| **C1.4 Alerts + staff** | alert feed over WebSocket, open/closed state, "pare angajat — confirmi?" card, photo upload for staff | confirm loop works end to end |
| **C1.5 Metrics** | FPS, verified ratio, latency, devices | numbers come from MQTT metrics |
| **C1.6 PWA** | manifest, service worker, Web Push for alerts, phone layout (alerts, new rule) | installable on a phone, push arrives |
| **C1.7 CI** | dashboard job: `npm ci && npm run lint && npm run build`; TS types generated from contracts | green |
| **C2.1 Site** | `apps/site` landing (problem, how it works, architecture, own solutions, impact, team), GitHub Pages workflow | live after the repo goes public (~Sat 09:00) |
| **C2.2 Docs** | README (pitch line, GIF, diagram, 3-command quickstart, badges), `docs/architecture.md` (Mermaid C4), ADRs 0001–0005, `docs/evals.md` | judges can run the demo from README |
| **C2.3 Pitch** | slides, demo script, backup video of every demo scene | rehearsed 3× before 10:30 Sat |

---

## Timeline and checkpoints

| Time | A (Vasi) | B (Marius) | C (Radu) |
|---|---|---|---|
| 10:50–11:40 | phone stream, models, FPS, record clips | Phase 0 scaffold + infra + CI | dashboard shell against mocks |
| 11:40–14:30 | A1.1–A1.4 | Phase 1 contracts → Phase 2 engine → B2.1, B2.3, B2.4 | C1.1, C1.2 |
| **14:30 M1** | **a person in a table zone for 1 min → Telegram alert via MQTT + Postgres** | | |
| 14:30–18:30 | A1.3 pose, A2.1 behaviour | B2.2, B2.5, B2.6 + evals | C1.3, C1.4 |
| **18:30 M2** | **rule from Romanian text; behaviour role; raised hand** | | |
| 19:30–00:00 | A2.2–A2.4 | B2.7, B3 hardening | C1.5, C1.6, C2.1 skeleton |
| **00:00 M3** | **feature freeze: appearance + confirm, queue, uncleared table, metrics** | | |
| 00:00–02:00 | bug fixes only | | |
| 02:00–06:00 | sleep in shifts | | |
| 06:00–09:00 | backup clips | evals numbers, gitleaks full history | site, docs, slides, backup video |
| ~09:00 | repo public, Pages live | | |
| **10:30 Sat** | **code freeze**, tag `v1.0` | | |

If M1 slips past 14:30, everyone drops their task and helps finish it.
