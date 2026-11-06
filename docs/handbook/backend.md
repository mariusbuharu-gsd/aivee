# Backend handbook — edge, MQTT, API, ingest, Postgres

## Run it

| Command | What |
|---|---|
| `make dev` | install the uv workspace (Python 3.12) — run first in every new worktree |
| `make data-dirs` | create `data/snapshots` and `recordings` as your user (run before the first `make up`, or Docker creates them as root) |
| `make up` / `make down` | Mosquitto :1883, Postgres+pgvector :5433, MediaMTX :8554/:8889, `migrate`, ingest ×2, api :8000 |
| `make seed` | demo org "AiVee Demo", location `demo` ("Terasa demo"), users `owner@` / `manager@` / `staff@aivee.demo`; password `DEMO_PASSWORD` (generated into `.env` when empty, never printed). Idempotent |
| `make api` | API on the host with reload (reads `.env`) |
| `make edge SOURCE=http://<phone>:8080/video` | real edge (needs `models/`, run from the repo root); `SOURCE` may also be a file |
| `make record SOURCE=… SECONDS=60 ROTATE=90 NAME=sala-1` | record a backup clip into `recordings/sala-1.mp4` (already rotated upright) |
| `make edge SOURCE=recordings/<name>.mp4` | replay a recorded clip through the real edge |
| `make fake-edge SCENARIO=unattended SPEED=10` | scripted people through the real edge pipeline (`unattended`, `hand`, `queue`, `uncleared`); zones and rules come from the retained config |
| `make test` / `make test-all` / `make lint` | unit / + integration (Docker) / ruff + mypy |
| `make schema` | regenerate JSON Schema from contracts |
| `make eval` | Romanian request → rule eval (21 cases, real API calls) |
| `make keys` / `make telegram-id` | paste API keys into `.env` / detect the Telegram group |
| `make vapid` | generate the Web Push VAPID keys into `.env` (never printed; kept if already set) |

`.env` holds every secret (names in `.env.example`); never print or commit values.
Models: `uv run python tools/download_models.py` → `models/` (gitignored).

## Environment (names only)

| Who reads it | Names |
|---|---|
| API | `SITE`, `DEVICE`, `MQTT_HOST`, `MQTT_PORT`, `MQTT_API_USER`, `MQTT_API_PASSWORD`, `SNAPSHOT_DIR`, `CORS_ORIGINS`, `COOKIE_SECURE`, `SESSION_TTL_HOURS`, `DASHBOARD_URL`, `CLAUDE_MODEL`, `YOLO_WEIGHTS`, `ANTHROPIC_API_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` |
| Ingest | `MQTT_HOST`, `MQTT_PORT`, `MQTT_INGEST_USER`, `MQTT_INGEST_PASSWORD`, `SNAPSHOT_DIR`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_PREFIX`, `VAPID_*`, `VERIFY_ALERTS`, `VERIFY_MODEL`, `VERIFY_TIMEOUT_S`, `ANTHROPIC_API_KEY` |
| Edge | `MQTT_HOST`, `MQTT_PORT`, `MQTT_EDGE_USER`, `MQTT_EDGE_PASSWORD`, `SITE`, `DEVICE`, `CAMERA_ID`, `SOURCE`, `TARGET_FPS`, `ROTATE`, `ARRIVE_S`, `DETECTOR_MODEL`, `POSE_MODEL`, `APPEARANCE`, `APPEARANCE_LOW`, `APPEARANCE_HIGH`, `STAFF_W_APPEARANCE`, `STAFF_W_STANDING`, `STAFF_W_BEHAVIOUR` |
| Postgres (all) | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST_PORT` |
| Seed / compose | `DEMO_PASSWORD`, `AIVEE_UID`, `AIVEE_GID`, `API_UV_EXTRAS` |

## Services

| Service | Code | Role |
|---|---|---|
| edge | `apps/edge` | camera → YOLO11n + ByteTrack → pose (table zones; everyone while appearance is scored) → stance + behaviour + CLIP → role → situation engine (opened / arrived / closed) → blurred snapshot → MQTT; live boxes on `detections` |
| ingest ×2 | `apps/ingest` | MQTT → Postgres; folds alert times; optional vision check of each opened alert (`verify.py`, `VERIFY_ALERTS`); audit `alert.*`, `device.*`; Telegram (location's `telegram_chat_id`, else `TELEGRAM_CHAT_ID`) + Web Push to the location's members and owners |
| api | `apps/api` | REST + WS; accounts, cookie sessions, roles per location, invites, audit; publishes retained edge state and staff commands; Claude translator; staff enrolment |
| mosquitto | `infra/mosquitto` | auth from `.env`, per-device ACL |
| postgres | `infra/postgres` | Postgres 17 + pgvector, Alembic migrations `0001`–`0008` (`migrate` service) |
| mediamtx | `infra/mediamtx` | RTSP in → WebRTC/WHEP out for the dashboard |

API code map (`apps/api/src/aivee_api/`): `auth/` (passwords, tokens, sessions, rate limit, permission
matrix, `require()`, scope helpers) · `accounts/` (models, invites, seed) · `locations/` (locations and
members) · `audit/` (append-only repository, summaries, router) · `alerts/` (lifecycle domain, ack, folded
views, service metrics) · `push/` (VAPID, subscriptions, sender) · `cameras/`, `zones/`, `rules/`,
`events/`, `devices/`, `staff/`, `metrics/`, `edge/` (MQTT link, retained sync, commands, live detections).

## Endpoints (from the routers)

Errors: `{detail: {code, message_ro}}`; 401 `unauthenticated`, 403 `forbidden`, 404 also for another
location's resources. `?location_id=` defaults to the caller's first location.

| Method | Path | Permission / notes |
|---|---|---|
| GET | `/healthz` | public |
| POST | `/api/auth/register` | public; creates org + owner, sets the cookie (201) |
| POST | `/api/auth/login` · `/api/auth/logout` | public / session; sets / clears `aivee_session` |
| GET | `/api/auth/me` | session → `Me` (org, `is_owner`, locations with role and permissions) |
| GET / POST | `/api/locations` | visible locations / create (owner) |
| PATCH / DELETE | `/api/locations/{id}` | `locations.manage` |
| GET | `/api/locations/{id}/members` | `users.manage` |
| PATCH / DELETE | `/api/locations/{id}/members/{user_id}` | `users.manage` (managers: staff only) |
| POST | `/api/invites` | `users.manage` → `{invite_url, expires_at}` (7 days) |
| GET | `/api/invites/{token}` | public: org, location, role, email |
| POST | `/api/invites/{token}/accept` | public `{name, password}` → `Me`, sets the cookie; single use |
| GET | `/api/audit` | `?location_id&actor&kind&from&to&before&limit` → `{items, next_before}`; owner org / manager location / staff own |
| GET / POST | `/api/cameras` | `alerts.view` / `devices.manage`; POST 409 on an existing id; only at the API's `SITE` |
| GET · PUT / PATCH | `/api/cameras/{id}` | `alerts.view` · `devices.manage` (name, source, device; zones kept) |
| GET / PUT | `/api/cameras/{id}/zones` | `alerts.view` / `devices.manage` (PUT replaces all) |
| GET / POST | `/api/rules` | `rules.manage` |
| GET / PATCH / DELETE | `/api/rules/{id}` | `rules.manage` |
| POST | `/api/rules/from-text` | `rules.manage`; `{camera_id, text, save?}` → `{rule, explanation_ro, saved}` |
| GET | `/api/events` | `alerts.view`; raw AlertEvents + `device_id`, `snapshot_url` |
| GET | `/api/snapshots/{id}` | `alerts.view` (event) or `staff.review` (suggestion); blurred JPEG; `{event_id}-before` is an object change's before image, with the event's rights |
| GET | `/api/alerts` | `alerts.view`; `?state=opened|acknowledged|arrived|closed|open&limit` → `[AlertView]` |
| POST | `/api/alerts/{event_id}/ack` | `alerts.ack`; "Merg eu" → `AlertView`; 409 if taken or closed |
| GET | `/api/metrics/verification` | `alerts.view`; `?location_id` → `{location_id, counts: [{rule_id, status, alerts}]}` |
| GET | `/api/metrics/service` | `alerts.view`; `?from&to` → wait / reaction / travel `{count, median_s, p90_s}` |
| GET | `/api/metrics` | `alerts.view`; FPS, CPU, verified ratio, events today, alert latency |
| GET | `/api/devices` | `alerts.view` |
| GET | `/api/staff/suggestions` | `staff.review` |
| POST | `/api/staff/suggestions/{id}/confirm` · `/reject` | `staff.review`; sends an EdgeCommand |
| GET | `/api/staff/profiles` · POST `/api/staff/photos` | `staff.enrol`; multipart `photo` or `files` (≤ 50 MB each) |
| GET | `/api/push/public-key` | public; 503 without VAPID keys |
| POST / DELETE | `/api/push/subscribe` | session; the subscription belongs to the user |
| POST | `/api/push/test` | session; test push to the caller's own devices → `{sent, removed, failed}` |
| WS | `/ws/events` | session cookie; `alert` (AlertView on every change), `suggestion`, `detections`; only the user's locations; 1008 without a session |

## MQTT topics (always via `aivee_contracts.topics.Topics`)

Root `aivee/<site>/<device>/…`, where `<site>` is the location id.

| Leaf | Direction | QoS / retain | Payload |
|---|---|---|---|
| `status` | edge → | 1, retained, LWT `offline` | DeviceStatus |
| `events` | edge → | 1 | AlertEvent (`opened` / `arrived` / `closed`) |
| `metrics` | edge → | 0 | Metrics (every 5 s) |
| `suggestions` | edge → | 1 | StaffSuggestion |
| `snapshots/<id>` | edge → | 1 | blurred JPEG bytes (event or suggestion id); `snapshots/<id>-before` (`Topics.snapshot_before`) for an `object_gone` alert |
| `detections` | edge → | 0, not retained, ≤ 5 Hz | Detections `{camera_id, ts, tracks: [{track_id, bbox (x1,y1,x2,y2 normalised), role, staff_score, raised_hand}], objects}`; the API forwards them on `/ws/events` |
| `rules` | → edge | 1, retained | RuleSet (complete) |
| `config` | → edge | 1, retained | DeviceConfig: cameras + zones (complete) |
| `profiles` | → edge | 1, retained | StaffProfiles (complete) |
| `commands` | → edge | 1, not retained | EdgeCommand `{command_id, kind: confirm_staff | reject_staff, camera_id, track_id, suggestion_id, at}`; the edge drops a redelivered `command_id` |

Ingest: `$share/ingest/aivee/+/+/events` (split between replicas) plus `status`, `suggestions`, `snapshots/+`
and `metrics` on every replica. ACL: each edge user writes only its own device topics (`%u`), so `DEVICE`
must equal `MQTT_EDGE_USER` (`edge-01`).

## API endpoints

The auth, locations, members, invites, audit and alert endpoints are listed in
`docs/plans/2026-11-06-auth-roles-audit.md`. Additions since then:

| Method | Path | Permission | Body → Response |
|---|---|---|---|
| DELETE | `/api/cameras/{id}` | `devices.manage` at the camera's location (else 404) | → 204. Zones and rules go too; events and alerts stay. Open alerts close as `closed_by: "system"`, `closed_reason: "camera_deleted"`. Retained `config` and `rules` are republished. Audit `camera.deleted` (`before` = the camera) + `alert.closed` per open alert |
| GET | `/api/invites?location_id=` | `users.manage` (default: first location) | → `[{id, email, role, location_id, created_by: {id, name} \| null, created_at, expires_at}]`, newest first, pending only (not accepted, revoked or expired). A manager sees only `staff` invites |
| DELETE | `/api/invites/{id}` | `users.manage`; a manager may revoke only `staff` invites (else 403) | → 204, idempotent. 404 outside the caller's locations, 409 if already accepted. Audit `user.invite_revoked` (once) |

A revoked invite's link (`GET /api/invites/{token}`, `POST …/accept`) answers 410
`{detail: {code: "gone", message_ro: "Invitația a fost anulată."}}`. Neither the token nor its hash is returned.

## Edge pipeline facts
- INT8 OpenVINO on the i7-1355U: ~20 FPS detection, ~12 FPS with pose; phone stream 8–11 FPS in practice.
- Phone camera over USB (`make edge-usb`: `adb forward tcp:28080 tcp:8080`, edge reads `http://localhost:28080/video`):
  stable 15 fps, while venue Wi-Fi stalled the MJPEG stream up to 1.8 s. `Cv2Source` emits a frame only after
  1/`TARGET_FPS` s, so set `TARGET_FPS` above the source rate (≥ 2×, e.g. 30 for 15): the default 10 against a
  15 fps stream drops every other frame and runs at ~7 fps.
- Engine `grace_s=5` (`GRACE_S`): a guest missing for up to 5 s still counts as present, so an alert closes ~5 s after
  the guest leaves (1.5 s closed alerts on detector flicker at low fps); tracks forgotten after 5 s; role hysteresis 0.7 / 0.4 (staff at ≥ 0.7, back to guest at ≤ 0.4); owner confirm / reject overrides.
- Staff score (`domain/role.py`): `(w_a·appearance + w_s·standing + w_b·behaviour) / Σ w of the signals available`,
  defaults `STAFF_W_APPEARANCE=0.60`, `STAFF_W_STANDING=0.25`, `STAFF_W_BEHAVIOUR=0.15`. Standing counts only next to
  appearance: with no appearance score (no profiles, or not embedded yet) the score is behaviour alone, so standing
  never makes anyone staff by itself. Enrolled staff standing still ≈ 0.85; a guest who stands up but does not look
  like staff tops out at 0.40.
- Appearance (`domain/appearance.py`): best CLIP cosine to a profile mapped linearly from `APPEARANCE_LOW=0.70`
  (→ 0) to `APPEARANCE_HIGH=0.82` (→ 1). Measured live (ViT-B-32 laion2b, 9-photo profile): the enrolled person
  0.82–0.91, seated guests in other clothes 0.60–0.64; the old 0.18–0.30 band saturated everyone at 1.
- Standing (`domain/stance.py`): per frame, the knee angle (hip–knee–ankle, pixel space) of the straightest visible
  leg: ≥ 150° standing (also mid-stride), ≤ 120° seated. Without a decisive leg, the box's pixel height / width:
  ≥ 2.2 standing, ≤ 1.6 seated, else unknown. The trajectory buffer keeps 3 s of known stances per track;
  `standing_ratio` = standing share × min(1, known span / 2 s), so a guest who just stood up does not count at once.
- `arrived`: a staff track's foot point in the alert's zone ≥ `ARRIVE_S` (default 5 s), once per alert.
- Appearance is off by default (`APPEARANCE` / `--appearance`), ~0.6 s per crop, at most once per 2 s per person.
- `ROTATE=90` for a sideways phone (D13). Live alert time is wall clock.
- Network sources (`rtsp://`, `http://`) decode on one FFmpeg thread (`Cv2Source._open`): frame threading held ~1 frame per core, ~2.4 s behind the camera at 5 fps on 12 cores. One thread still decodes 1280×720 at ~34 FPS.

- `object_gone` (`domain/objects.py`): objects count by their box base (bottom-centre) inside the zone, per class;
  the level is the highest count of the last `GONE_CONFIRM_S=3` s, so flicker does not count. A drop below the level
  after `min_duration_s` (at least 3 s) holds until the object reappears or `GONE_HOLD_S=30` s pass: the alert opens
  once and closes by itself. The pipeline keeps per zone the last frame that showed every object and sends it
  blurred as `snapshots/<id>-before`; the event carries `object_change {kind: gone, objects, before_snapshot}`.

## Alert verification (ingest, `VERIFY_ALERTS`, default off)
`apps/ingest/.../verify.py`: `AlertVerifier` port, `ClaudeAlertVerifier` (`messages.parse`, `VERIFY_MODEL`, effort low,
`VerificationAnswer`). The question is built from the rule's `prompt_ro`; `object_gone` sends before + after, other kinds
the opened snapshot. Runs as a task (the handler never waits), once per alert (atomic `pending` claim), `VERIFY_TIMEOUT_S`
(20 s). Confirmed → notify with the model's summary; rejected → no notification; unavailable (off, no key, error,
timeout, no image) → normal alert. Results on the opened row (`verification_*`, `verified_at`, migration `0008`);
`AlertView.verification`, `before_snapshot_url`. Design: `docs/plans/2026-11-06-object-change-design.md`.

## Request → rule
`apps/api/.../rules/translator.py`: `messages.parse`, model `claude-opus-5-5`, effort low, `RuleDraft` output;
fixed instructions first, camera zones last (cache-friendly). Handles refusal / max_tokens / SDK errors with
Romanian messages. Eval: `evals/nl_to_rule` — 20/20, median 2.4 s (21 cases since `gone-glass`, not re-run yet).

## Known gaps
- Login rate limit is in memory: a restart clears it, and several API processes would count separately.
- Staff photo profiles are global, not per location: every location's edge gets the same StaffProfiles.
- Cameras can be added only at the location of the API's edge link (`SITE` / `DEVICE`); other locations
  get "Locația nu are un dispozitiv conectat la acest server."
- Alerts stay open when a device goes offline (no close or arrival comes) — being fixed in `fix/alert-edge-cases`.
- Web Push needs HTTPS on phones (secure context); plain `http://<laptop-ip>` gets Telegram only.
- `test_fake_edge_alert_is_acknowledged_arrives_and_closes` (integration) failed in 2 of 3 full
  `-m integration` runs on 2026-11-06 and passes alone: timing-sensitive.
