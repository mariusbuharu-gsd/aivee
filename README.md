<p align="center">
  <img src="docs/brand/aivee-logo.svg" alt="AiVee" height="56" />
</p>

<p align="center">
  <a href="https://github.com/mariusbuharu-gsd/aivee/actions/workflows/ci.yml"><img alt="ci" src="https://github.com/mariusbuharu-gsd/aivee/actions/workflows/ci.yml/badge.svg?branch=develop" /></a>
  <a href="LICENSE"><img alt="MIT licence" src="https://img.shields.io/badge/licence-MIT-14161B" /></a>
</p>

> **People learn too late what happens in front of their cameras, because nobody has time to watch them.**

AiVee is the staff's extra pair of eyes for restaurants, terraces and events. **No hardware to buy:
plug in the cameras you already have**, draw the tables, write a rule in Romanian, and AiVee alerts the
waiters on their phone when a guest waits too long. It tells staff from guests by uniform and behaviour,
never by face.

- **Cloud (standard, live).** Cameras send frames to one shared AiVee server, where a vision worker per
  camera analyses them and discards them; video is never stored. It runs today at
  <https://app-aivee.earth.sv.gsd.com.ro>: a laptop webcam or an IP camera joins through the connector script
  (`apps/connector`, Windows, Linux, macOS), a phone through the `/telefon` page.
- **Edge (option).** The same pipeline runs on the customer's own PC or on our edge box, for maximum
  privacy or offline use: video never leaves the location. It runs on a plain laptop CPU
  ([measured](#measured-performance)).

Decision: [D25](docs/decisions.md), [ADR 0011](docs/adr/0011-cloud-or-edge-analysis.md). The demo runs in
cloud mode on that server, with a laptop on the table as the camera; the laptop stack (`make up`) is the
edge mode and the fallback.

Built at Astra Hack, Innovation Week Sibiu, 6–7 November 2026.

> **Live:** presentation site https://aivee.earth.sv.gsd.com.ro · app https://app-aivee.earth.sv.gsd.com.ro (demo accounts on request; the demo is the 4-minute run in [docs/demo-script.md](docs/demo-script.md)).

## Features

| | |
|---|---|
| **Situations** | unattended table · guest raises a hand · queue at the entrance · table not cleared · an object appears or goes missing. One situation engine (present / absent / count / pose / objects + duration). |
| **Visual rules (fire, smoke, …)** | A `visual` condition scores CLIP prompts ("a photo of fire") against negative prompts ("a photo of a normal room") above a threshold for a minimum time: „Foc în imagine” → „…: posibil foc”. |
| **Rules in Romanian** | "Anunță ospătarul dacă la o masă nu a venit nimeni de 1 minut" → a typed `Rule` draft the owner confirms, edits or discards. Vague or out-of-scope requests get a question back. |
| **Staff by appearance + behaviour** | CLIP embedding of the staff's look plus movement (tables visited, distance per minute). Suggested staff are confirmed with one tap: "Pare angajat — confirmi?". |
| **Staff enrolment in 20 s** | A guided 20 s capture from a live camera (Dispozitive), or the `/angajat-nou` page on a phone: name, film the colleague, save. No photo sorting. |
| **Privacy by design** | No face recognition, faces blurred in every snapshot. Cloud: video analysed and discarded, never stored, EU servers. Edge: video never leaves the location. See [Privacy](#privacy-by-design). |
| **Alerts that close themselves** | opened → arrived (the camera sees staff in the zone for ≥ 5 s) → closed. Nobody presses a button. While nobody has arrived, a ⏰ reminder every `REMIND_S` („⏰ Încă neservit: Masa 1, de 2 min”); if the guest leaves first, „👋 Clientul a plecat … fără să fie servit”. Each alert shows the wait; Metrici shows the median and p90. |
| **Alerts on the phone** | Telegram message with a blurred snapshot; on arrival it is edited to „✅ Rezolvat · un angajat a ajuns după …” and reminders are replies to it. Installable PWA with Web Push: the notification opens the alert. |
| **Any camera, three ways in** | An RTSP / IP camera or a laptop webcam through the connector script (`apps/connector`, Python + ffmpeg, Windows / Linux / macOS); a phone through the `/telefon` page (no app); or a local edge on the same machine. |
| **Live detection overlay** | Live video with a box per person, light blue for staff and white for guests, streamed from the edge at up to 5 Hz. |
| **Accounts and roles per location** | Owner (every location), manager and staff per location, a fixed permission matrix enforced in the API, invites by link, sessions in an HttpOnly cookie. |
| **Multi-location** | Organization → locations (restaurant, terrace, event, shop, other) → devices. Each location has its own team, rules, alerts and Telegram chat. |
| **Audit history** | Append-only log, enforced in Postgres: logins, config changes with before/after, staff decisions, alerts, devices. Shown on Istoric. |

## Architecture

```mermaid
flowchart LR
    cam["Camera<br/>RTSP / MJPEG"] --> edge
    subgraph site["One machine (edge mode, as built)"]
        edge["Edge (CPU)<br/>YOLO11n INT8 OpenVINO + ByteTrack<br/>pose · role · situation engine<br/>arrival · face blur"]
        mq[("Mosquitto<br/>ACL · LWT · retained")]
        ing["ingest ×2<br/>shared subscription"]
        pg[("Postgres 17 + pgvector<br/>tenancy · append-only audit")]
        api["API (FastAPI)<br/>cookie sessions · roles per location"]
        mtx["MediaMTX"]
    end
    edge -- "events · status · metrics<br/>snapshots · detections" --> mq
    mq -- "rules · config · profiles (retained)<br/>commands" --> edge
    mq --> ing --> pg
    ing --> tg["Telegram"]
    ing --> wp["Web Push"]
    api <--> pg
    api -- "publish complete state · commands" --> mq
    mq -- "metrics · detections" --> api
    api -- "request → rule" --> claude["Claude API"]
    dash["Dashboard + PWA (React)"] <-- "REST + WS (cookie)" --> api
    edge --> mtx -- WebRTC --> dash
    wp --> dash
```

The diagram above is edge mode: everything on one machine. Cloud mode, live on the server, runs the same
pipeline behind HTTPS ([ADR 0011](docs/adr/0011-cloud-or-edge-analysis.md),
[cloud-mode handbook](docs/handbook/cloud-mode.md)):

```mermaid
flowchart LR
    subgraph venue["Restaurant"]
        cam["IP camera / laptop webcam"] --> con["connector script<br/>640 px · 5 fps JPEG"]
        phone["Phone<br/>/telefon page"]
    end
    subgraph cloud["AiVee server (HTTPS only)"]
        api["API<br/>POST /api/ingest/frames/&lt;camera&gt;<br/>newest frame in memory"]
        mq[("Mosquitto")]
        vis["vision worker<br/>one per camera<br/>(the edge pipeline)"]
        ing["ingest"]
        pg[("Postgres")]
    end
    con -- HTTPS --> api
    phone -- HTTPS --> api
    api -- "frames/&lt;camera&gt; (QoS 0)" --> mq --> vis
    vis -- "events · metrics · snapshots" --> mq --> ing --> pg
    ing --> tg["Telegram · Web Push"]
    api -- "live.mjpg" --> dash["Dashboard"]
```

Frames are never written to disk: the API keeps only the newest one per camera.

More: [docs/architecture.md](docs/architecture.md) (context and containers, tenancy, auth and permissions,
audit, alert lifecycle and request → rule sequences, MQTT topics, scalability) and the [ADRs](docs/adr/):

1. [Edge-first CPU inference with OpenVINO](docs/adr/0001-edge-first-cpu-inference.md)
2. [MQTT with ACL, LWT, retained state, shared subscriptions](docs/adr/0002-mqtt-acl-lwt-retained-shared.md)
3. [Postgres 17 + pgvector](docs/adr/0003-postgres-pgvector.md)
4. [Contracts as the single source of truth](docs/adr/0004-contracts-single-source-of-truth.md)
5. [Staff by appearance + behaviour, no face recognition](docs/adr/0005-staff-by-appearance-and-behaviour.md)
6. [LLM turns the request into a rule, human confirms](docs/adr/0006-llm-request-to-rule.md)
7. [Opaque sessions in an HttpOnly cookie, not JWT](docs/adr/0007-session-cookie-not-jwt.md)
8. [Roles per location with a fixed permission matrix](docs/adr/0008-roles-per-location-fixed-matrix.md)
9. [Append-only audit log, enforced in the database](docs/adr/0009-append-only-audit-log-in-db.md)
10. ["Arrived" detected on the edge, not self-reported](docs/adr/0010-arrival-detected-on-edge.md)
11. [Cloud or edge analysis, per customer](docs/adr/0011-cloud-or-edge-analysis.md) (partly supersedes ADR 1)

## Tech stack

| Layer | Tech |
|---|---|
| Edge | Python 3.12, Ultralytics YOLO11n + pose, OpenVINO INT8 (NNCF), ByteTrack, OpenCLIP, OpenCV, paho-mqtt |
| Messaging | Eclipse Mosquitto 2 (per-device ACL, LWT, retained, QoS 1, shared subscriptions) |
| Backend | FastAPI, SQLAlchemy 2 (async) + asyncpg, Alembic, aiomqtt, Anthropic SDK (structured outputs), argon2-cffi, pywebpush (VAPID) |
| Data | Postgres 17 + pgvector |
| Video | MediaMTX (RTSP in, WebRTC/WHEP out) |
| Frontend | Vite 8, React 19, React Router, TypeScript strict, plain CSS on design tokens, vite-plugin-pwa + Workbox; static site in plain HTML/CSS |
| Contracts | Pydantic → JSON Schema → TypeScript types |
| Tooling | uv workspace, ruff, mypy (strict on contracts and edge domain), pytest + testcontainers, Vitest, ESLint, GitHub Actions, gitleaks |

## Quickstart

Needs Docker, [uv](https://docs.astral.sh/uv/) and Node 24.

```bash
cp .env.example .env     # fill in the names listed there (or: make keys; make vapid for push)
make dev                 # install the Python workspace
make data-dirs           # data/snapshots and recordings, owned by you
make up                  # Mosquitto, Postgres+pgvector, migrations, MediaMTX, ingest ×2, API :8000
make seed                # demo org, location `demo`, owner@ / manager@ / staff@aivee.demo
                         # (password DEMO_PASSWORD in .env)
make fake-edge SCENARIO=unattended SPEED=10   # scripted scenario through the real pipeline
                                              # (unattended | hand | queue | uncleared)
cd apps/dashboard && npm ci
VITE_API_URL=http://localhost:8000 npm run dev   # dashboard; omit VITE_API_URL for the offline mock
```

Open `http://localhost:5173/intra` and log in as `owner@aivee.demo`.

With a real camera: `uv run python tools/download_models.py`, then
`make edge SOURCE=http://<phone>:8080/video ROTATE=90` (Android IP Webcam stream). Backup clip:
`make record SOURCE=http://<phone>:8080/video SECONDS=60 ROTATE=90 NAME=sala-1`, replay with
`make edge SOURCE=recordings/sala-1.mp4`. The 4-minute demo: [docs/demo-script.md](docs/demo-script.md)
(operations: [docs/demo-runbook.md](docs/demo-runbook.md)).

### Cloud deploy

The shared server runs the stack `aivee-demo` on Docker Swarm: images, services, env names, migrations
and one vision worker per camera are in [deploy/aivee-demo/README.md](deploy/aivee-demo/README.md). To add a
camera from anywhere: [cloud-mode handbook](docs/handbook/cloud-mode.md) (connector script or `/telefon`).
All commands: [backend handbook](docs/handbook/backend.md) · [frontend handbook](docs/handbook/frontend.md).

## Repository map

```
apps/
  edge/        camera → detection, tracking, pose, role, situation engine, arrival, blur → MQTT
               domain/ is pure (no IO) behind Protocol ports; adapters/ for YOLO, CLIP, MQTT, blur;
               also the cloud vision worker (SOURCE=mqtt-frames://<camera>)
  connector/   restaurant side of cloud mode: camera / webcam → HTTPS frames or RTSP (stdlib + ffmpeg)
  ingest/      shared-subscription worker → Postgres (alert times, audit) → Telegram + Web Push,
               alert lifecycle (✅ edit, reminders, client left)
  api/         FastAPI: REST + WS, accounts, roles per location, invites, audit, alert lifecycle,
               retained edge state, request → rule, staff enrolment, push, Alembic
  dashboard/   React 19 dashboard + PWA (Romanian UI)
  site/        static presentation site (served from our server)
packages/
  contracts/   Pydantic models + MQTT topic builder → JSON Schema → TS types
infra/         mosquitto, postgres, mediamtx config
evals/         nl_to_rule: 20 Romanian requests → expected rules
tools/         fake_edge.py, record_clip.py, bench_edge.py, download_models.py, gen_vapid.py, setup scripts
deploy/        aivee-demo: the Docker Swarm stack of the shared server
docs/          architecture, ADRs, decisions log, handbooks, plans, demo script and runbook, brand
```

## How we test

| Suite | Command | Result (2026-11-07) |
|---|---|---|
| Python unit | `uv sync --all-packages -q && uv run pytest -q` | 706 passed ¹ |
| Python integration (testcontainers: Mosquitto, Postgres + pgvector) | `uv run pytest -q -m integration` | 189 passed, 3 skipped |
| Dashboard (Vitest) | `cd apps/dashboard && npm ci && npx vitest run` | 356 passed (47 files) |
| Request → rule eval (real API calls) | `make eval` | not rerun; last run 2026-11-06: 20/20, median 2.4 s, max 4.0 s |

¹ One test, `test_background_scorer_keeps_one_frame_in_flight`, is timing-sensitive: on 2026-11-07 it failed
in the first full run (705 passed, 1 failed), then passed in a second full run and 3 of 3 runs alone.

Unit tests cover the situation engine on simulated timelines (cooldown, arrival after `ARRIVE_S`, close),
behaviour and role scoring, zone geometry, the permission matrix cell by cell, sessions and the login rate
limit, alert lifecycle times and percentiles, the lifecycle texts, the connector, and push. Integration tests cover MQTT → Postgres (duplicates
ignored), LWT → offline, retained state on reconnect, pgvector lookups, login and invites, scoping between
locations and organizations, the audit log rejecting UPDATE / DELETE, the fake edge → arrived → closed
lifecycle, the ✅ / 👋 Telegram edits, reminders claimed once across two replicas, and HTTPS camera frames
through the real Mosquitto ACL. CI runs lint, mypy, all Python tests with coverage,
contract drift checks (JSON Schema and TS types), the dashboard lint/tests/build, the site build and a
gitleaks scan of the full history.

## Privacy by design

Two modes, two honest claims:

| Cloud (standard) | Edge (option) |
|---|---|
| Video is analysed and discarded, never stored. | Video never leaves the location. |
| Servers in the EU. | Analysis runs on the customer's PC or our edge box. |
| What is kept: alerts, metrics, audit history and blurred snapshots. | What leaves: alerts, metrics and blurred snapshots, over MQTT. |

In both modes:

- **Faces blurred in every snapshot**, before it is stored or sent (Telegram, push, dashboard).
- **Role, not identity.** AiVee decides only "guest" or "staff", from uniform and movement. No face
  recognition (GDPR art. 9 biometrics, EU AI Act); requests to recognise a person are refused.
- **The rule request sends text only** to the Claude API, never images.
- **Least access.** Staff see only their location's alerts; the history records who did what and cannot be edited.
- **Human in the loop.** Rules are drafts until the owner confirms them; suggested staff are confirmed
  or rejected explicitly.

## Measured performance

Measured per camera stream, on a laptop CPU with no GPU: the pipeline is cheap to run, which is what makes
edge mode on an ordinary PC possible. Cloud cost per stream is not measured yet, so we quote none.

| What | Number | Setup |
|---|---|---|
| Detection | ~20 FPS | YOLO11n INT8 OpenVINO, i7-1355U CPU, no GPU |
| Detection + pose | ~12 FPS | pose only inside table zones |
| Phone camera stream | 8–11 FPS | Android IP Webcam, 640×480 MJPEG (the camera is the bottleneck) |
| Romanian request → rule | 20/20, median 2.4 s | `evals/nl_to_rule`, see [results](evals/nl_to_rule/results.md) |

## Design system

Logo, colours, type and voice: [docs/brand/README.md](docs/brand/README.md) (tokens in
[docs/brand/tokens.css](docs/brand/tokens.css)).

## Team

Marius Buharu · Radu Nedela · Vasi Dancu

<!-- TODO(team): add roles. -->

## Licensing

- **Our code is MIT** ([LICENSE](LICENSE)), and stays open (decision [D26](docs/decisions.md)).
- **The detector is not.** The edge depends on [Ultralytics YOLO](https://github.com/ultralytics/ultralytics)
  (`ultralytics` 8.4.203 in `uv.lock`), licensed **AGPL-3.0**.
- **What that means.** AGPL-3.0 also covers software used over a network. When we run the pipeline in our
  cloud, or distribute it on an edge box or a customer's PC, the complete source of what runs, including our
  changes, must be available to its users under AGPL-3.0. The alternative is an Ultralytics Enterprise
  licence. Anyone who redistributes AiVee with Ultralytics inherits the same obligation; AiVee's own files
  remain usable under MIT.
