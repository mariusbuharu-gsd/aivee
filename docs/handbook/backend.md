# Backend handbook — edge, MQTT, API, ingest, Postgres

## Run it

| Command | What |
|---|---|
| `make dev` | install the uv workspace (Python 3.12) — run first in every new worktree |
| `make data-dirs` | create `data/snapshots`, `data/videos` and `recordings` as your user (run before the first `make up`, or Docker creates them as root) |
| `make up` / `make down` | Mosquitto :1883, Postgres+pgvector :5433, MediaMTX :8554/:8889, `migrate`, ingest ×2, api :8000 |
| `make seed` | demo org "AiVee Demo", location `demo` ("Terasa demo"), users `owner@` / `manager@` / `staff@aivee.demo`; password `DEMO_PASSWORD` (generated into `.env` when empty, never printed). Idempotent |
| `make api` | API on the host with reload (reads `.env`) |
| `make edge SOURCE=http://<phone>:8080/video` | real edge (needs `models/`, run from the repo root); `SOURCE` may also be a file |
| `make record SOURCE=… SECONDS=60 ROTATE=90 NAME=sala-1` | record a backup clip into `recordings/sala-1.mp4` (already rotated upright) |
| `make edge SOURCE=recordings/<name>.mp4` | replay a recorded clip through the real edge |
| `make fake-edge SCENARIO=unattended SPEED=10` | scripted people through the real edge pipeline (`unattended`, `hand`, `queue`, `uncleared`); zones and rules come from the retained config |
| `make test` / `make test-all` / `make lint` | unit / + integration (Docker) / ruff + mypy |
| `make schema` | regenerate JSON Schema from contracts |
| `make eval` | Romanian request → rule eval (30 cases, real API calls) |
| `uv run python tools/visual_probe.py IMG_OR_VIDEO "positive" … --negative …` | CLIP score of a visual rule's prompts per image / frame (calibration, see „Reguli libere”) |
| `make keys` / `make telegram-id` | paste API keys into `.env` / detect the Telegram group |
| `make vapid` | generate the Web Push VAPID keys into `.env` (never printed; kept if already set) |

`.env` holds every secret (names in `.env.example`); never print or commit values.
Models: `uv run python tools/download_models.py` → `models/` (gitignored).

## Environment (names only)

| Who reads it | Names |
|---|---|
| API | `SITE`, `DEVICE`, `MQTT_HOST`, `MQTT_PORT`, `MQTT_API_USER`, `MQTT_API_PASSWORD`, `SNAPSHOT_DIR`, `CORS_ORIGINS`, `COOKIE_SECURE`, `SESSION_TTL_HOURS`, `DASHBOARD_URL`, `CLAUDE_MODEL`, `YOLO_WEIGHTS`, `ANTHROPIC_API_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`, `VIDEO_DIR`, `VIDEO_PYTHON`, `MQTT_UPLOAD_USER`, `MQTT_UPLOAD_PASSWORD`, `TELEGRAM_BOT_USERNAME` (optional), `TELEGRAM_BOT_TOKEN` (only for getMe when the username is empty) |
| Ingest | `MQTT_HOST`, `MQTT_PORT`, `MQTT_INGEST_USER`, `MQTT_INGEST_PASSWORD`, `SNAPSHOT_DIR`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_PREFIX`, `TELEGRAM_POLL`, `PUBLIC_DASHBOARD_URL` (optional), `REALERT_AFTER_S`, `REMIND_S` (default 120, 0 = off), `VAPID_*`, `VERIFY_ALERTS`, `VERIFY_MODEL`, `VERIFY_TIMEOUT_S`, `ANTHROPIC_API_KEY` |
| Edge | `MQTT_HOST`, `MQTT_PORT`, `MQTT_EDGE_USER`, `MQTT_EDGE_PASSWORD`, `SITE`, `DEVICE`, `CAMERA_ID`, `SOURCE`, `TARGET_FPS`, `ROTATE`, `ARRIVE_S`, `DETECTOR_MODEL`, `POSE_MODEL`, `APPEARANCE`, `APPEARANCE_LOW`, `APPEARANCE_HIGH`, `STAFF_W_APPEARANCE`, `STAFF_W_STANDING`, `STAFF_W_BEHAVIOUR`, `VISUAL_HZ`; clip runs also `CLIP_EPOCH`, `PROGRESS_FILE`, `CONFIG_WAIT_S` (set by the API) |
| Postgres (all) | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST_PORT` |
| Seed / compose | `DEMO_PASSWORD`, `AIVEE_UID`, `AIVEE_GID`, `API_UV_EXTRAS` |

## Services

| Service | Code | Role |
|---|---|---|
| edge | `apps/edge` | camera → YOLO11n + ByteTrack → pose (table zones; everyone while appearance is scored) → stance + behaviour + CLIP → role → situation engine (opened / arrived / closed) → blurred snapshot → MQTT; live boxes on `detections` |
| ingest ×2 | `apps/ingest` | MQTT → Postgres; folds alert times; optional vision check of each opened alert (`verify.py`, `VERIFY_ALERTS`); audit `alert.*`, `device.*`; Telegram (location's `telegram_chat_id`, else `TELEGRAM_CHAT_ID`) + Web Push to the location's members and owners; the "Conectează Telegram" getUpdates poller (`telegram_link.py`, one replica) |
| api | `apps/api` | REST + WS; accounts, cookie sessions, roles per location, invites, audit; publishes retained edge state and staff commands; Claude translator; staff enrolment |
| mosquitto | `infra/mosquitto` | auth from `.env`, per-device ACL |
| postgres | `infra/postgres` | Postgres 17 + pgvector, Alembic migrations `0001`–`0010` (`migrate` service) |
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
| GET | `/api/capabilities` | signed in; `{videos, enrol}`: the clip runner (same checks as `POST /api/videos`) and the staff enroller are wired on this server |
| GET / POST | `/api/locations` | visible locations / create (owner) |
| PATCH / DELETE | `/api/locations/{id}` | `locations.manage` |
| POST | `/api/locations/{id}/telegram/link` | `locations.manage` → `{url, private_url, expires_at}`: `https://t.me/<bot>?startgroup=<code>` / `?start=<code>`; single use, 15 min; 503 without a bot username |
| GET | `/api/locations/{id}/telegram` | `locations.manage` → `{connected, chat_title}` |
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
| GET | `/api/cameras/{id}/frame` | `alerts.view`; the camera's newest face-blurred still (today: its latest alert's whole-frame snapshot), time in `X-Frame-At`, `no-store`; 404 until one exists |
| POST | `/api/ingest/frames/{camera_id}` | HTTP Basic `STREAM_PUBLISH_USER/PASSWORD` (constant-time); body one JPEG ≤ 500 KB, or (no Authorization header) the session cookie with `devices.manage` at the camera's location, only for a cloud camera (`source` = `mqtt-frames://<id>`, else 409; 403 without the permission) — the dashboard's `/telefon` page → 204. 401 credentials, 413 size, 415 not JPEG (magic bytes), 404 unknown camera. Kept in memory as the camera's newest frame and relayed on `frames/<camera>` of the camera's device. Cloud mode over HTTPS: [cloud-mode.md](cloud-mode.md) |
| GET | `/api/cameras/{id}/live.mjpg` | `alerts.view`; `multipart/x-mixed-replace` of the posted frames, ≤ 5 fps (`LIVE_FPS`), `no-store`, `X-Accel-Buffering: no`; 404 while no frame came in the last 10 s; ends when the client leaves or after 30 s without frames. In memory, single api replica only |
| GET | `/api/alerts` | `alerts.view`; `?state=opened|acknowledged|arrived|closed|open&limit` → `[AlertView]` |
| POST | `/api/alerts/{event_id}/ack` | `alerts.ack`; "Merg eu" → `AlertView`; 409 if taken or closed |
| GET | `/api/metrics/verification` | `alerts.view`; `?location_id` → `{location_id, counts: [{rule_id, status, alerts}]}` |
| GET | `/api/metrics/service` | `alerts.view`; `?from&to` → wait / reaction / travel `{count, median_s, p90_s}` |
| GET | `/api/metrics` | `alerts.view`; FPS, CPU, verified ratio, events today, alert latency |
| GET | `/api/devices` | `alerts.view` |
| GET | `/api/staff/suggestions` | `staff.review` |
| POST | `/api/staff/suggestions/{id}/confirm` · `/reject` | `staff.review`; sends an EdgeCommand |
| GET | `/api/staff/profiles` · POST `/api/staff/photos` | `staff.enrol`; multipart `photo` or `files` (≤ 50 MB each) |
| POST | `/api/staff/capture` | `staff.enrol` on the camera's location; `{camera_id, seconds: 5–30 (20)}`. Samples the camera's in-memory live frames every 1.5 s, keeps only the largest person per frame → `{token, frames, candidates: [{index, thumbnail (data URL)}], expires_in_s}`. Lasts ≈ `seconds`. 404 no live frames, 422 nobody found, 503 no models |
| POST | `/api/staff/capture/frames` | `staff.enrol` (`?location_id`); multipart `frames` (≤ 30 JPEGs, ≤ 2 MB each) a phone took itself → the same CaptureOut as `/api/staff/capture` (`camera_id: ""`), confirm the same way. 413 too large, 422 not JPEG / too many / nobody found, 503 no models |
| POST | `/api/staff/capture/{token}/confirm` | same user only; `{keep: [index], name, description_ro?, profile_id?}` → EnrolOut; new profile `staff-<hex>` unless `profile_id`; publishes profiles; token used once, kept 10 min in memory (single replica) |
| GET | `/api/push/public-key` | public; 503 without VAPID keys |
| POST / DELETE | `/api/push/subscribe` | session; the subscription belongs to the user |
| POST | `/api/push/test` | session; test push to the caller's own devices → `{sent, removed, failed}` |
| POST | `/api/videos` | `devices.manage`; multipart `file` (mp4/mov/webm, ≤ 200 MB, ≤ 2 min), `location_id` (form or query), `rotate` 0/90/180/270, `copy_from_camera_id` → 201 VideoOut; 422 type/size/length/unreadable, 503 without `MQTT_UPLOAD_PASSWORD`; only at the API's `SITE` |
| GET | `/api/videos?location_id=` · `/api/videos/{id}` | `devices.manage`; `{status: queued\|running\|done\|failed, progress 0–1, duration_s, events, error_ro, …}`, newest first |
| GET | `/api/videos/{id}/events` | `devices.manage`; the clip's alerts by `at_s` (clip position), `arrived_at_s`, `closed_at_s`, `closed_reason` (`video_end` = open when the clip ended), `snapshot_url` |
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
| `frames/<camera>` (`Topics.frames`) | api → vision worker | 0, not retained | JPEG bytes posted to `/api/ingest/frames/<camera>`; read by `SOURCE=mqtt-frames://<camera>` (ACL `pattern read aivee/+/%u/frames/#`) |

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

## Conectează Telegram (one-click chat link)

`aivee_api/locations/telegram.py` + `aivee_ingest/telegram_link.py`, migration `0010_telegram_links`.
- The API stores only the sha256 of a random 16-character code (`telegram_links`: location, creator,
  `expires_at` = +15 min, `used_at`, `chat_id`). The bot username is `TELEGRAM_BOT_USERNAME`, else one
  `getMe` with `TELEGRAM_BOT_TOKEN`, cached after success.
- Ingest long-polls `getUpdates` (offset, timeout 25 s). `/start <code>` (private) or `/start@<bot> <code>`
  (group, sent by Telegram after `?startgroup=`) → `consume_link`: saves `telegram_chat_id` and
  `telegram_chat_title` on the location, marks the code used, audits `location.telegram_connected` (actor:
  the user who created the link) and replies "✅ AiVee e conectat la «…». Aici vor veni alertele."
  Expired / used / unknown codes get a Romanian reply; the same chat sending the same code again (a
  redelivered update) gets none. `my_chat_member` updates carry no payload and are ignored.
- **One poller.** Telegram allows one `getUpdates` caller per bot (a second one, or a webhook, gets 409).
  Every ingest replica runs the loop, but only the holder of the Postgres session advisory lock
  `POLL_LOCK_KEY` polls; the others retry every 30 s and take over when the holder's connection goes away.
  `TELEGRAM_POLL=false` turns the loop off on an instance. A 409 is logged and retried after 60 s; other
  errors after 5 s. The loop never stops the notifier.
- While ingest polls, `make telegram-id` (also `getUpdates`) conflicts with it and sees no updates: use
  "Conectează Telegram" instead, or set `TELEGRAM_POLL=false` and restart ingest first.
- A manual chat id (PATCH `telegram_chat_id`) clears the stored title.

## Telegram alert message and "Preiau ✋"

`aivee_ingest/alert_message.py` (pure) + `telegram.py` + `telegram_ack.py`.
- Format (photo caption, or text without a snapshot), `parse_mode=HTML`, every name escaped:
  `🔴 <b>headline</b>` / explanation / blank / `📍 location · camera · HH:MM` (Europe/Bucharest).
  Names come from the DB (`locations.alert_context`: site, camera, zone, rule, verification); ids
  only when a name is missing. The branch is the rule's most specific condition, in the edge's
  order: object_gone ("Masa 1: a dispărut un pahar de vin" / "Verifică masa."), visual ("Sala principală:
  posibil foc"), object_present ("Terasă: a apărut un urs"), pose ("Masa 2: un
  client cheamă"), objects_unattended ("Masa 3 e nedebarasată de 3 min"), count ("Bar: 4 persoane
  așteaptă"), absent ("Masa 1 așteaptă de 1 min" / "Nu a venit nimeni la client."), present; no
  rule → the edge's `summary_ro`. A confirmed vision check's `summary_ro` is the explanation.
- Inline keyboard: `Preiau ✋` (`callback_data` `ack:<alert id>`) and, only when
  `PUBLIC_DASHBOARD_URL` is https with a public host, `Vezi în aplicație` → `<url>/alerte`.
- A 400 on the rich send is retried once as plain `sendMessage` without keyboard or parse mode.
- The getUpdates poller (`allowed_updates` = message, my_chat_member, callback_query) hands a
  button press to `AlertCallbacks`: only from the chat the alert went to (the location's chat,
  else `TELEGRAM_CHAT_ID`); `AlertRepository.acknowledge` with the sender's first name
  (`acknowledged_by_id` empty: no AiVee account) and audit `alert.acknowledged` (actor
  `telegram:<user id>`, `after.via = telegram`). Toasts: "Preluată ✓" (the message gets
  "✋ Preluată de Ana · 16:58" and loses the button), "Deja preluată de X", "Alerta s-a închis"
  (button removed). No "X merge la" Web Push for a Telegram ack (that one is sent by the API).
- Not done: editing the message to "✅ Rezolvată" on close needs the sent message id stored
  per alert (a migration); closed events are split between replicas, so memory will not do.

## Video analysis (uploaded clips)

Design: [plans/2026-11-06-video-upload-design.md](../plans/2026-11-06-video-upload-design.md). The API queues
clips (one at a time) and runs `python -m aivee_edge --clip-epoch …` as the device `MQTT_UPLOAD_USER`
(`upload-01`, `%u` ACL) on camera `video-<id>`, which carries a copy of a live camera's zones and rules.
How an alert ends (ingest, `lifecycle.py`): on `arrived` the follow-up "Un angajat a ajuns…" goes out and
the original Telegram alert is edited to "✅ Rezolvat · un angajat a ajuns după 25 s · preluată de Ana" without
buttons; a `closed` with no arrival (re-checked after 3 s, in case the `arrived` is still on its way) sends
"👋 Clientul a plecat de la Masa 1 fără să fie servit (a așteptat 3 min 10 s)" and edits the original to
"⚪ Închisă · clientul a plecat" (object/visual rules get neutral wording); a device going offline edits its
open alerts the same way. The Telegram chat and message id are kept on the opened row
(`events.telegram_chat_id`, `telegram_message_id`, `telegram_photo`). While an alert is open and nobody
arrived, every `REMIND_S` the location gets "⏰ Încă neservit: Masa 1, de 4 min" (Telegram: a reply to the
alert with the same buttons; Web Push: kind `realert`), claimed atomically on `events.reminded_at` so it goes
out once per period whatever the replica count, and survives restarts. "Preiau" never closes an alert.

Event time = clip epoch + clip position. Ingest never notifies, verifies, re-alerts or audits alerts from
an `upload-*` device or a `video-*` camera, and the device going offline closes nothing; the API closes what
is still open as `video_end`. Upload alerts stay out of alerts, the live feed, events, metrics, devices,
cameras and rules. The run's log is `VIDEO_DIR/<id>.log`. Analysis needs the edge next to the API
(`make api` on the host; the compose image only with `API_UV_EXTRAS="--extra ml"`).

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
Romanian messages. Eval: `evals/nl_to_rule` — 30/30, median 2.7 s (2026-11-06, with the open-rule cases);
each run also writes `drafts.json` (raw model output per case), the source of `tests/fixtures/recorded_drafts.json`.

## Reguli libere (open rules: `object_present`, `visual`)

The owner can ask for anything a camera image shows: „anunță-mă dacă vine un urs”, „dacă e foc”,
„dacă iese fum”, „dacă e apă pe jos”, „dacă intră un câine”, „dacă cineva are un cuțit”, „dacă ușa
rămâne deschisă”. Refusals do not change: faces, identifying people, age, gender, ethnicity and any
judgement of a person's appearance stay refused; theft is only `object_gone` (an object gone from a table).

**How it works.**
1. *Translation* (`rules/prompt.py`, situations 6 and 7). A COCO class → `object_present` (`objects`,
   `min_duration_s` 2). Anything else visible (fire, smoke, water or a spill on the floor, an open door,
   broken glass, a fight) → `visual`: the model writes 2-3 English CLIP prompts in `positive`, 4-6 in
   `negative` (always "a photo of a person", "a photo of a room", "a blurry photo" plus the normal look of
   the place), `min_duration_s` 3, `threshold` 0.5, `crop` "frame" or null, and a Romanian `label_ro`
   ("foc"). `cooldown_s` 120. `object_present` is preferred when a COCO class fits. The API refuses
   `object_present` names outside the 80 COCO classes.
2. *Where.* A rule that names no place (or a place with no zone, „în bucătărie”) gets `zone_tag:
   "anywhere"` (`ANYWHERE_TAG` in contracts). Nobody draws it: the edge adds a pseudo-zone with id and tag
   `anywhere`, the whole image, named after the camera, only while an enabled rule uses it
   (`domain/visual.py: with_whole_frame`). Every person and object in the image is in it, edges included,
   so the alert reads „Sala principală: posibil foc”, and the API / ingest take the zone name from the
   summary. The API accepts `anywhere` only for rules made of open conditions.
3. *Edge, `object_present`* (`zone_state.py`): the YOLO detections already there; an object counts by its
   base (bottom-centre), with the engine's grace. The detector's class filter (`DEFAULT_CLASSES`) is
   extended at run time with the classes of enabled `object_present` rules (`YoloDetector.set_extra_classes`,
   log `detector_classes extra=bear`); unknown names are logged as `detector_unknown_classes`.
4. *Edge, `visual`* (`domain/visual.py`, `adapters/clip_visual.py`): the `VisualScorer` port is CLIP
   ViT-B-32 (laion2b), the same weights as the appearance embedder plus its text encoder. Prompt
   embeddings are computed once per rule load and cached. Score = softmax over [positive…, negative…]
   with the model's temperature (`logit_scale` = 100); the positive probability is the sum over the
   positive prompts. Crop: the zone's bounding box, or the whole frame for `crop: "frame"` and for
   `anywhere`. Scoring runs on one background thread (2 torch threads), one frame in flight, at most
   `VISUAL_HZ` times per second (default 2) and only while an enabled visual rule exists; the CLIP weights
   load on the first visual rule (log `visual_model_loaded`). Offline clip runs score inline. A run starts
   at the first sample at or above `threshold` and holds `min_duration_s`; a sample below it ends the run
   only once the last one above is more than `GRACE_S` old, so one bad sample does not reset it and the
   alert closes about `GRACE_S` after the scene stops matching. Capture gaps freeze it like other timers.
   Log `visual_score ms=… jobs=… scores=<rule>/<zone>=0.97` every 5 s (every sample at DEBUG).
5. *Both kinds* open and close through the same engine path as the other kinds: cooldown, snapshot on
   open, arrival, grace, stream gaps. Nothing changes for the existing kinds.
6. *Verification* (`verify.py`, `VERIFY_ALERTS`): the snapshot is checked with the „visible” question,
   built from the rule's `prompt_ro` and `label_ro`: „Se vede cu adevărat în imagine: foc? Răspunde da doar
   dacă este real în scenă, nu pe un ecran, poster sau telefon…”. **This is the main false-alarm guard
   for open rules**: rejected means no notification. Keep `VERIFY_ALERTS=true` when open rules are on.
7. *Message* (`alert_message.py`): „🔴 Sala principală: posibil foc” / „Verifică imediat locul.” and
   „🔴 Terasă: a apărut un urs” / „Verifică locul.”; a confirmed check replaces the second line with its
   summary. Dashboard: the card reads Unde / Ce caută / Cât timp / Atunci.

**Calibration** (`tools/visual_probe.py`, 2026-11-06; `apps/edge/tests/fixtures/` holds two public-domain
images, licences in `LICENSES.md`). Fire prompts ["a photo of fire", "flames"] vs the five recommended
negatives: campfire photo 1.000, cv2-synthetic flames 0.997, the fire pasted over 60 % of a restaurant
snapshot 0.625, over 30 % 0.058; 16 real face-blurred room and person snapshots 0.000-0.048, bear photo
0.002. A bear prompt: bear photo 1.000, everything else ≤ 0.036 (but 0.000 for the bear pasted over 40 % of
a room snapshot, which YOLO finds as `bear` 0.79: use `object_present` for animals and objects). Scores are
nearly binary (logit scale 100), so the default `threshold` is **0.5** (`VISUAL_THRESHOLD`): well above every
normal room, below a fire filling half the image. Without the generic negatives the same fire prompts gave
0.99 on a person crop and 0.99 on a bear: the negatives matter more than the threshold. Re-tune on the real
camera with the probe on recorded frames before relying on a rule.

**Limits.** CLIP is coarse: fire on a TV or phone screen counts, so does a red-lit crowd (a football photo
with a red blurred background scored 0.93 for fire); small or distant things are missed (a fire over 30 %
of the image scored 0.06); it sees one frame, not motion (smoke and a fight are guesses). Every alert is
double-checked by the vision model before anyone is told, and the alert stays visible as „Neconfirmat”
when rejected.

**Costs.** Edge: about 0.15 s of CLIP per sample on 2 threads (median 156 ms, p90 219 ms measured with a
busy machine), so ~0.3 core at `VISUAL_HZ=2`; the pipeline thread pays ~10 µs per frame (hand-off only).
Text encoding ~0.1 s per new prompt, once per rule load. Memory: the CLIP weights (~600 MB) load only with
the first visual rule (shared with appearance). Cloud: one translator call per rule and one verification
call per opened alert (as every other kind); `cooldown_s` 120 bounds the alerts per zone.

| Env | Default | Meaning |
|---|---|---|
| `VISUAL_HZ` (edge) | 2 | CLIP scorings per second while a visual rule is enabled; 0 turns visual rules off on this edge |
| `GRACE_S` (edge) | 5 | also how long a visual or object_present condition may drop before its alert closes |
| `VISUAL_THRESHOLD` (contracts constant) | 0.5 | default `threshold` of a visual condition |

## Known gaps
- Login rate limit is in memory: a restart clears it, and several API processes would count separately.
- Staff photo profiles are global, not per location: every location's edge gets the same StaffProfiles.
- Cameras can be added only at the location of the API's edge link (`SITE` / `DEVICE`); other locations
  get "Locația nu are un dispozitiv conectat la acest server."
- Alerts stay open when a device goes offline (no close or arrival comes) — being fixed in `fix/alert-edge-cases`.
- Web Push needs HTTPS on phones (secure context); plain `http://<laptop-ip>` gets Telegram only.
- `test_fake_edge_alert_is_acknowledged_arrives_and_closes` (integration) failed in 2 of 3 full
  `-m integration` runs on 2026-11-06 and passes alone: timing-sensitive.
