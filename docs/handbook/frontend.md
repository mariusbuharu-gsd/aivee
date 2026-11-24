# Frontend handbook — dashboard, PWA, site, design

## Dashboard (`apps/dashboard`)

- Stack: Vite 8, React 19, React Router, TypeScript strict, Vitest, ESLint + Prettier. No UI kit.
- Run against the mock: `npm ci && npm run dev` (no `VITE_API_URL`) — a demo timeline plays, and the login
  page offers the demo accounts. Camere → Adaugă cameră demos the whole setup: the box of *Terasa demo*
  finds two Tapo cameras and a Hikvision (the Tapo at `192.168.1.20` is already added), the password
  `gresit` is refused (`camera_auth`), and *Bistro Centru*'s box is switched off (the "no box" state).
- Run against the real stack: `make data-dirs && make up && make seed` in the repo root, then
  `VITE_API_URL=http://localhost:8000 npm run dev` and log in as `owner@aivee.demo` (password `DEMO_PASSWORD`
  in `.env`). Live video: `VITE_WHEP_BASE` (default `http://localhost:8889`).
- On a phone in the same Wi-Fi: `npm run dev -- --host`, `VITE_API_URL=http://<laptop-ip>:8000`, and add
  `http://<laptop-ip>:5173` to `CORS_ORIGINS`. Push needs HTTPS (see below).
- Env names: `VITE_API_URL`, `VITE_WHEP_BASE`.
- Checks before a PR: `npm run lint && npx vitest run && npm run build` (plus `npm run e2e` locally before a release), and
  `npm run contracts && git diff --exit-code src/contracts`.

### End-to-end tests (Playwright, `e2e/`)
- `npm run e2e` (or `make e2e`): a production build on the built-in mock, in Chrome on desktop and on a
  Pixel 7 viewport. Needs nothing running; not part of CI — run it before a release. First time locally: `npx playwright install chromium`.
- `npm run e2e:real`: the same app against a running API (`make api` + `make seed`). Reads `E2E_API_URL`
  (default `http://localhost:8000`) and `DEMO_PASSWORD` from the environment; it serves on :5174, which the
  API's CORS allows. These tests are read-only.
- `e2e/mock/` covers sign-in and `?next=`, sign-out, invites, the role matrix per page, the location switcher,
  the alert timeline (no "Preiau"), history filters, metrics, two cameras on one location (Live, staff
  without video, the zone editor's camera switch) adding an IP camera by brand (`cameras.spec.ts`), and the "Caută camere" wizard: discover → pick → test →
  name → zones, a refused Tapo password with the guide, no box online (`camera-setup.spec.ts`).
  `e2e/real/` asserts each role loads its pages
  without any 4xx from the API (the anonymous `/api/auth/me` probe excepted).
- Failures keep a trace and screenshot in `test-results/`; open one with `npx playwright show-trace <zip>`.

### Screens (UI copy in Romanian)

Public: `/intra` (login, `?next=` return), `/cont-nou` (new organization + owner), `/invitatie/:token`
(accept an invite). Everything else needs a session; a 401 sends you to `/intra?next=…`.

| Route | Page | Permission | Purpose |
|---|---|---|---|
| `/` | Live | `alerts.view` | camera tiles with live video and detection boxes (staff light blue, guests white) for `devices.manage` only (`canWatchLive`): staff (waiters) get the open alerts as cards with the blurred snapshot, never live video; one state per camera (`src/devices/health.ts`: the API's per-camera `stream_state` decides `down` / `reconnecting`; with `ok` or null the camera follows its device and its `last_seen`, polled every 5 s; `last_frame_at` is shown for a stopped camera, never aged, since the edge republishes only once a minute), an offline camera is one row "Cameră offline" with the cause; alert feed, staff suggestions; "Configurare" checklist for owners and managers (8 steps from cameras, zones, rules, staff profiles, push/Telegram; `src/setup/checklist.ts`), one line ("Mai ai 2 pași: …" + "Arată") once ≤ 2 steps are left, "Conectează Telegram" inline for owners, "Ascunde" remembered per user on the device |
| `/alerte` | Alerte | `alerts.view` | alerts with the timeline Deschisă → Ajuns → Închisă with the wait (no "Preiau": the camera closes alerts; a "Preluată" step shows only on old alerts that were taken); AI verification badge ("Confirmat de AI" / "Neconfirmat" / "Se verifică…") with Înainte / După thumbnails for object_gone; "Notificări pe telefon" |
| `/metrici` | Metrici | `alerts.view` | service times (Așteptare: median and p90, from arrival times; the Reacție and Drum tiles are hidden since nobody takes alerts), FPS, CPU, verified frames |
| `/reguli` | Reguli | `rules.manage` | write a rule in Romanian (or dictate) → "Ce am înțeles" draft → Confirmă și salvează / Modifică; "Exemple" per location type (`src/rules/templates.ts`) only fill the text; open rules („dacă e foc”, „dacă vine un urs”) read Unde / Ce caută / Cât timp / Atunci, `anywhere` shows as „oriunde în imagine” (`src/rules/chips.ts`) |
| `/dispozitive` (alias `/camere`) | Camere | `devices.manage` | one card per camera with its state (as on Live), "Testează" on IP camera cards (`camera_test`: the box opens the saved camera by `camera_id`, the password is never resent; dialog with the still or the problem and a fix hint), "Adaugă cameră": when `/api/capabilities` says `camera_discovery`, a wizard (`components/AddCameraWizard.tsx`) with no IPs, RTSP, ids or box names on the owner's way: 1 the box (picked by itself when the location has one online; none → „Cutia AiVee nu e pornită sau nu e conectată” and what to check; several → „Cutia AiVee 1/2” with the cameras each serves), 2 „Caută camere” (up to ~10 s with a progress bar; brand, model or name, IP; `already_added` greyed out as „Deja adăugată”; „Nu-mi găsești camera? Adaug-o manual” opens the form below), 3 user and password + „Testează” (Tapo: an inline, collapsible 3-step guide to the camera account, opened by a `camera_auth`; other brands one line), 4 a name (id generated from it, `src/devices/discovery.ts`), 5 the zone editor. The source is built from IP, port, the first `rtsp_paths` entry and the account. Without `camera_discovery`, or by „Adaug-o manual”: *Cameră IP* (brand Tapo / Hikvision / Dahua / Reolink / Altă marcă, IP, user, password → the substream RTSP address from `src/devices/rtsp.ts`, e.g. Tapo `rtsp://{user}:{pass}@{ip}:554/stream2`, shown only with the password masked under "Avansat, pentru instalator"; "Testează camera" only when `/api/capabilities` says `camera_test`), *Telefon* (a cloud camera, then the QR) or *Altă sursă* (raw address); a second camera defaults to the device of the first; "Editează camera" asks IP, user and a new password (empty keeps it) and never shows the stored one; for a cloud camera (`mqtt-frames://<id>`) the card menu has "Folosește telefonul": a QR to `<origin>/telefon?camera=<id>`; every camera has "👔 Adaugă angajat" (`staff.enrol`): name → live preview + 20 s capture → untick candidates → save publishes the profile; device id, source, FPS/CPU and the latency line sit under "Detalii tehnice"; an online device silent for > 60 s shows "fără imagine"; the offline checklist asks about the laptop script and `/telefon` for `mqtt-frames://` sources |
| `/angajat-nou` | Adaugă angajat (one phone) | `staff.enrol` | the phone films the employee itself, no stream: name or existing profile → `getUserMedia` preview (back camera, front/back toggle, `object-fit: contain`) → Start: a JPEG every 1.5 s for 20 s (`src/staff/burst.ts`, long side ≤ 640 px) → `POST /api/staff/capture/frames` → untick candidates → confirm. Camera tracks stop after the upload. Linked from the Personal card and as a QR in the camera dialog ("Fă-o de pe telefon") |
| `/telefon` | Telefonul ca cameră | `devices.manage` | the phone browser becomes a cloud camera: `getUserMedia` (back camera, front/back toggle) → always a 640x360 canvas, the video contain-fitted with black bars (a portrait phone arrives whole, never cropped, so zones and boxes line up with the 16:9 Live tile and zone editor; the preview is 16:9 too, with the hint "Ține telefonul pe orizontală pentru imagine întreagă") → JPEG 0.7 → `POST /api/ingest/frames/<id>` with the session cookie at 5 fps, one request in flight (`src/phone/sender.ts` skips frames instead of queueing); status Trimite / Reconectare… / Oprit, frames/s, Screen Wake Lock. Needs HTTPS (or localhost) |
| `/camere/:cameraId/zone` | Zone editor | `devices.manage` | a "Camera" switch when the location has several (asks about unsaved changes first); draw polygons on the live frame, else the camera's newest blurred still (`captureFrame`), or an uploaded still; zones save per camera; tags `table`, `entrance`, `staff` (shown as „Zonă angajați”) |
| `/video` | Testează pe un clip | `devices.manage` | upload a clip (≤ 200 MB, ≤ 2 min), copy zones and rules from a camera, optional rotation; list with status and progress; timeline of the alerts found (mm:ss in the clip); never notifies staff |
| `/istoric` | Istoric | `audit.view` / `audit.view.own` | audit history with filters (actor, kind, period); read-only |
| `/echipa` | Echipă | `users.manage` | members, roles, invite link |
| `/locatii` | Locații | `locations.manage` | the organization's locations (owner); in the edit form "Conectează Telegram" opens the bot link in a new tab, polls the status every 3 s for up to 15 min and shows "Conectat: <grup>"; the manual chat id sits under "Avansat" (no QR: there is no QR library in the deps) |

The sidebar groups the pages: what happens now, Configurare, Administrare, then Avansat (Istoric,
Locații). Reguli and Testează pe un clip open on the first online camera that has zones or rules
(`src/devices/defaultCamera.ts`). The sidebar has a location switcher when the user has more than one location; every page reads the current
location. `can(permission)` hides actions and routes; the API is what enforces them.

### Code map
`src/api/` client interface, `mock.ts`, `mockAccounts.ts`, `http.ts` (`credentials: 'include'`, 401 → login),
`socket.ts` (one shared `/ws/events` socket per tab, back-off 1–15 s; after a reconnect, and when the tab
becomes visible, `LiveData` reloads alerts, lifecycles, cameras and suggestions; live alerts of other
locations are dropped) · pages other than Login and Live are `React.lazy` chunks (`App.tsx`) ·
`src/auth/` AuthProvider, RequireAuth, session helpers · `src/contracts/` generated types (never edit) ·
`src/zones/geometry.ts` pure polygon logic · `src/alerts/fold.ts`, `format.ts` · `src/rules/describe.ts` ·
`src/live/` WHEP player and detection overlay · `src/pwa/`, `src/push/` · `src/state/` shared state ·
`src/components/`, `src/pages/` · `src/styles.css`.

## API the frontend uses

Base `VITE_API_URL`, always with the session cookie. Errors: `{detail: {code, message_ro}}` — show
`message_ro`. Most calls take `?location_id=`. Full list with permissions: [backend handbook](backend.md#endpoints-from-the-routers).

| Method | Path | Notes |
|---|---|---|
| POST | `/api/auth/login` · `/register` · `/logout` | login / register return `Me` and set the cookie |
| GET | `/api/capabilities` | `{videos, enrol, camera_test?, camera_discovery?}`: optional features this server runs; `videos: false` hides „Testează pe un clip” and sends `/video` to Live (a failed call hides nothing); `camera_test` shows every „Testează”, `camera_discovery` the add-camera wizard |
| POST | `/api/devices/{device_id}/discover` | `discoverCameras()`: 200 `{cameras: [{ip, port, brand: tapo\|hikvision\|dahua\|reolink\|unknown, model, name, onvif, rtsp_paths, already_added}]}`; 409 `device_offline`, 504 `device_timeout` (takes up to ~10 s) |
| POST | `/api/cameras/test?location_id=` | `testCamera()`: body `{source, camera_id, device}` (unset ones null; a saved camera by `camera_id` only) → 200 `image/jpeg` + `X-Frame-At`, `X-Frame-Size`; 422 `camera_auth` \| `camera_unreachable` \| `camera_no_stream` \| `device_required`, 409 `device_offline`, 504 `device_timeout`. The UI shows `message_ro`, with Romanian fallbacks and a fix hint per code (`src/devices/cameraProblems.ts`) |
| GET | `/api/auth/me` | `{user, org, is_owner, locations: [{id, name, type, role, permissions}]}` |
| GET/POST · PATCH/DELETE | `/api/locations` · `/api/locations/{id}` | owner |
| POST · GET | `/api/locations/{id}/telegram/link` · `/api/locations/{id}/telegram` | owner; `{url, private_url, expires_at}` · `{connected, chat_title}` |
| GET · PATCH/DELETE | `/api/locations/{id}/members` · `.../members/{user_id}` | Echipă |
| POST · GET · POST | `/api/invites` · `/api/invites/{token}` · `/api/invites/{token}/accept` | invite link, public preview, accept |
| GET | `/api/audit` | `{items: [AuditEntry], next_before}`; filters `actor`, `kind`, `from`, `to`, `before` |
| GET/POST | `/api/cameras` | POST accepts `id`; 409 on an existing id |
| GET · PUT/PATCH | `/api/cameras/{id}` | includes `online` |
| GET/PUT | `/api/cameras/{id}/zones` | PUT replaces all zones |
| GET/POST | `/api/rules` · GET/PATCH/DELETE `/api/rules/{id}` | |
| POST | `/api/rules/from-text` | `{camera_id, text, save?}` → `{rule, explanation_ro, saved}`; may answer a clarifying question |
| GET | `/api/alerts?state=&limit=` | folded `AlertView` with `wait_s`, `reaction_s`, `travel_s`, `unacknowledged_arrival`, `verification {status, summary_ro, object_ro}` and `before_snapshot_url` (object_gone) |
| POST | `/api/alerts/{event_id}/ack` | "Preiau" (no longer offered in the UI); 409 when someone already took it |
| GET | `/api/metrics/service?from&to` | `{alerts, unacknowledged_arrivals, wait, reaction, travel}`, each `{count, median_s, p90_s}` |
| GET | `/api/events?limit=` · `/api/snapshots/{id}` | raw events · blurred JPEG |
| POST | `/api/ingest/frames/{id}` | `pushFrame()`: one JPEG body (`image/jpeg`) from `/telefon`; 204, 401 / 403 / 409 (not a cloud camera) stop the sender |
| GET | `/api/cameras/{id}/frame` · `/api/devices` | `captureFrame()`: newest blurred still + `X-Frame-At` · devices with `last_seen` |
| POST | `/api/videos` | multipart `file` (mp4/mov/webm, ≤ 200 MB, ≤ 2 min), `location_id`, optional `rotate` (0/90/180/270), `copy_from_camera_id` → 201 `VideoUpload`; 422 bad type/size/length |
| GET | `/api/videos?location_id=` | `VideoUpload[]`, newest first; the page polls every 2 s while one is queued or running |
| GET | `/api/videos/{id}` | `VideoUpload` (`status`, `progress` 0..1, `duration_s`, `events`, `error_ro`) |
| GET | `/api/videos/{id}/events` | `VideoAlert[]` by `at_s`; positions in the clip, `closed_reason: video_end`, `snapshot_url` |
| GET | `/api/devices` · `/api/metrics` | status, `last_seen` · `DashboardMetrics` (`alert_latency_ms` may be `null`) |
| GET | `/api/staff/suggestions` · POST `.../{id}/confirm` · `.../{id}/reject` | |
| GET | `/api/staff/profiles` · POST `/api/staff/photos` | multipart field `photo` (images or a short video) |
| POST | `/api/staff/capture` · `/api/staff/capture/{token}/confirm` | "Adaugă angajat" on a Dispozitive camera card (`components/StaffCapture.tsx`): capture ≈ 20 s, then confirm the kept candidates |
| GET | `/api/push/public-key` | VAPID key; 503 when the server has no keys |
| POST/DELETE | `/api/push/subscribe` | body = `PushSubscription.toJSON()` / `{endpoint}`; tied to the logged-in user |
| POST | `/api/push/test` | test push to the caller's devices → `{sent, removed, failed}` |
| WS | `/ws/events` | cookie-authenticated; `{type: 'alert', data: AlertView}` on every change, `{type: 'suggestion', data}`, `{type: 'detections', camera_id, data: [{track_id, role, box: [x,y,w,h], staff_score, raised_hand}]}`; only the user's locations |

Contract types: `packages/contracts` → `make schema` → `npm run contracts`. Don't hand-write API types.

## Design system

- One palette, from the logo. The source of truth is `docs/brand/tokens.css`, and the rules are in `docs/brand/README.md`.
  Its `:root` block is copied to the top of `src/styles.css`. Use only the variables, never raw hex values.
- The look is a light working surface (`--ground` `#F6F7F9`, `--surface` white, `--ink` `#14161B` text) with night
  chrome: the sidebar, camera media and the suggestion card are ink. Add `.on-night` to any dark container;
  it remaps `--text`, `--surface*`, `--border*` and `--focus`.
- Coral `#FF5C6C` means "needs attention" (open alerts). Use it for fills only.
  As text on light, use `--coral-strong` `#C8283E`. On camera media, light blue (`--live-on-night`) marks staff
  and live, and white/grey marks guests and tables.
- Fonts: Fredoka 600 for the logo and h1, Figtree for the UI, JetBrains Mono for ids, timers and metrics.
  Tap targets are at least 44 px.
- Brand files are in `docs/brand/` (logo, white logo, mark, app icon, favicon).
- Must work at 390 px (waiters use phones) and 1440 px (owner at a laptop). Alerts are glanceable: zone name,
  how long, one action.
- Privacy is visible: faces are blurred, staff confirmation is explicit ("Pare angajat — confirmi?").

## PWA and push (`src/pwa/`, `src/push/`)
- `vite-plugin-pwa` (injectManifest): manifest colours are read from the `--ink` / `--ground` tokens,
  icons in `public/icons/` (rendered from `docs/brand/aivee-app-icon.svg`; maskable has a full-bleed ink ground).
- `src/pwa/sw.ts` precaches the app shell (offline navigation in production builds), shows push
  notifications and opens `/alerte` on tap. The API is never cached; `OfflineBanner` probes `/healthz`.
- Alerte page → "Notificări pe telefon": states indisponibil / blocate / oprite / active, plus "Trimite un test".
- Alerts are pushed to the subscribed members and owners of the alert's location; the arrival follow-up
  replaces the alert's notification (same tag).
- Push needs a secure context: `localhost` or HTTPS. On a phone, serve the dashboard and the API over HTTPS
  (e.g. `tailscale serve`), add that origin to `CORS_ORIGINS` and set `COOKIE_SECURE=true`.

## Presentation site (`apps/site`)
Static HTML/CSS, built by `apps/site/build.mjs`, deployed to GitHub Pages by `.github/workflows/pages.yml`.
- One page told as a scroll story: the hero eyes dive into the room, then one evening replays in five
  beats, then the reference sections (how it works, scenarios, privacy, team, impact, demo, pilot,
  architecture, team).
- Modules in `src/`: `story.js` (dive, story timeline, typing rule), `eyes.js` (pupils follow the pointer
  inside a circular clamp), `nav.js`, `contact.js` (copy buttons), `form.js` ("Cere un demo" opens a
  prefilled `mailto:`; there is no backend).
- Motion is opt-in: `<head>` sets `html.js` and, unless the visitor prefers reduced motion, `html.motion`.
  Only then does `story.js` load the self-hosted GSAP, ScrollTrigger and Lenis from `src/vendor/`
  (licences in `src/vendor/LICENSES.md`; GSAP is not MIT). Without JS or with reduced motion the page is
  a still, complete layout: no smooth scroll, no pinning.

## Known gaps
- WHEP live video checked only headless (black frame) — verify in a real browser before the demo.
- Push does not work from a phone over plain `http://<laptop-ip>` (no secure context); Telegram still does.
- Staff photo profiles are global (shared by every location), not per location.
- Cameras can be added only at the API's own location (`SITE`); elsewhere "Adaugă cameră" gets an error.
- Open alerts stay open when their device goes offline — being fixed in `fix/alert-edge-cases`.
- **Generated camera ids.** The wizard names a camera `cam-<slug of its name>` (e.g. `cam-sala-mare`). An
  edge box (`make edge-box`) runs whatever cameras the dashboard configures. Only an edge started with
  the `CAMERAS` dev override ignores ids it does not know; for such an edge, add the camera with
  „Adaug-o manual” and the id from `CAMERAS` under „Avansat”.