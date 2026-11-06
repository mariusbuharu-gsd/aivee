# Frontend handbook — dashboard, PWA, site, design

## Dashboard (`apps/dashboard`)

- Stack: Vite 8, React 19, React Router, TypeScript strict, Vitest, ESLint + Prettier. No UI kit.
- Run against the mock: `npm ci && npm run dev` (no `VITE_API_URL`) — a demo timeline plays, and the login
  page offers the demo accounts.
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
  API's CORS allows. These tests are read-only except "Merg eu", which writes only the audit log.
- `e2e/mock/` covers sign-in and `?next=`, sign-out, invites, the role matrix per page, the location switcher,
  "Merg eu" and the alert timeline, history filters, metrics. `e2e/real/` asserts each role loads its pages
  without any 4xx from the API (the anonymous `/api/auth/me` probe excepted).
- Failures keep a trace and screenshot in `test-results/`; open one with `npx playwright show-trace <zip>`.

### Screens (UI copy in Romanian)

Public: `/intra` (login, `?next=` return), `/cont-nou` (new organization + owner), `/invitatie/:token`
(accept an invite). Everything else needs a session; a 401 sends you to `/intra?next=…`.

| Route | Page | Permission | Purpose |
|---|---|---|---|
| `/` | Live | `alerts.view` | camera tiles, live video with detection boxes (staff light blue, guests white), alert feed, staff suggestions |
| `/alerte` | Alerte | `alerts.view` | alerts with "Merg eu" and the timeline Deschisă → Preluată → Ajuns → Închisă with reaction / travel / wait; AI verification badge ("Confirmat de AI" / "Neconfirmat" / "Se verifică…") with Înainte / După thumbnails for object_gone; "Notificări pe telefon" |
| `/metrici` | Metrici | `alerts.view` | service times (Așteptare, Reacție, Drum: median and p90), FPS, CPU, verified frames |
| `/reguli` | Reguli | `rules.manage` | write a rule in Romanian (or dictate) → "Ce am înțeles" draft → Confirmă și salvează / Modifică |
| `/dispozitive` | Dispozitive | `devices.manage` | edge devices online/offline, "Adaugă cameră" |
| `/camere/:cameraId/zone` | Zone editor | `devices.manage` | draw polygons on a live frame or an uploaded still; tags `table`, `entrance`, `staff` |
| `/video` | Analiză video | `devices.manage` | upload a clip (≤ 200 MB, ≤ 2 min), copy zones and rules from a camera, optional rotation; list with status and progress; timeline of the alerts found (mm:ss in the clip); never notifies staff |
| `/istoric` | Istoric | `audit.view` / `audit.view.own` | audit history with filters (actor, kind, period); read-only |
| `/echipa` | Echipă | `users.manage` | members, roles, invite link |
| `/locatii` | Locații | `locations.manage` | the organization's locations (owner) |

The sidebar has a location switcher when the user has more than one location; every page reads the current
location. `can(permission)` hides actions and routes; the API is what enforces them.

### Code map
`src/api/` client interface, `mock.ts`, `mockAccounts.ts`, `http.ts` (`credentials: 'include'`, 401 → login) ·
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
| GET | `/api/auth/me` | `{user, org, is_owner, locations: [{id, name, type, role, permissions}]}` |
| GET/POST · PATCH/DELETE | `/api/locations` · `/api/locations/{id}` | owner |
| GET · PATCH/DELETE | `/api/locations/{id}/members` · `.../members/{user_id}` | Echipă |
| POST · GET · POST | `/api/invites` · `/api/invites/{token}` · `/api/invites/{token}/accept` | invite link, public preview, accept |
| GET | `/api/audit` | `{items: [AuditEntry], next_before}`; filters `actor`, `kind`, `from`, `to`, `before` |
| GET/POST | `/api/cameras` | POST accepts `id`; 409 on an existing id |
| GET · PUT/PATCH | `/api/cameras/{id}` | includes `online` |
| GET/PUT | `/api/cameras/{id}/zones` | PUT replaces all zones |
| GET/POST | `/api/rules` · GET/PATCH/DELETE `/api/rules/{id}` | |
| POST | `/api/rules/from-text` | `{camera_id, text, save?}` → `{rule, explanation_ro, saved}`; may answer a clarifying question |
| GET | `/api/alerts?state=&limit=` | folded `AlertView` with `wait_s`, `reaction_s`, `travel_s`, `unacknowledged_arrival`, `verification {status, summary_ro, object_ro}` and `before_snapshot_url` (object_gone) |
| POST | `/api/alerts/{event_id}/ack` | "Merg eu"; 409 when someone already took it |
| GET | `/api/metrics/service?from&to` | `{alerts, unacknowledged_arrivals, wait, reaction, travel}`, each `{count, median_s, p90_s}` |
| GET | `/api/events?limit=` · `/api/snapshots/{id}` | raw events · blurred JPEG |
| POST | `/api/videos` | multipart `file` (mp4/mov/webm, ≤ 200 MB, ≤ 2 min), `location_id`, optional `rotate` (0/90/180/270), `copy_from_camera_id` → 201 `VideoUpload`; 422 bad type/size/length |
| GET | `/api/videos?location_id=` | `VideoUpload[]`, newest first; the page polls every 2 s while one is queued or running |
| GET | `/api/videos/{id}` | `VideoUpload` (`status`, `progress` 0..1, `duration_s`, `events`, `error_ro`) |
| GET | `/api/videos/{id}/events` | `VideoAlert[]` by `at_s`; positions in the clip, `closed_reason: video_end`, `snapshot_url` |
| GET | `/api/devices` · `/api/metrics` | status, `last_seen` · `DashboardMetrics` (`alert_latency_ms` may be `null`) |
| GET | `/api/staff/suggestions` · POST `.../{id}/confirm` · `.../{id}/reject` | |
| GET | `/api/staff/profiles` · POST `/api/staff/photos` | multipart field `photo` (images or a short video) |
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
- Coral `#FF5C6C` means "needs attention" (open alerts, the one alert action "Merg eu"). Use it for fills only.
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
