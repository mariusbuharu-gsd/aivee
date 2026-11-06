# Frontend handbook — dashboard, PWA, site, design

## Dashboard (`apps/dashboard`)

- Stack: Vite 8, React 19, React Router, TypeScript strict, Vitest, ESLint + Prettier. No UI kit.
- Run against the mock: `npm ci && npm run dev` (no `VITE_API_URL`) — a 45 s demo timeline plays.
- Run against the real stack: `make up && make api` in the repo root, then
  `VITE_API_URL=http://localhost:8000 npm run dev`. Live video: `VITE_WHEP_BASE` (default `http://localhost:8889`).
- Checks before a PR: `npm run lint && npm test -- --run && npm run build && npm run e2e`, and
  `npm run contracts && git diff --exit-code src/contracts`.

### End-to-end tests (Playwright, `e2e/`)
- `npm run e2e` (or `make e2e`): a production build on the built-in mock, in Chrome on desktop and on a
  Pixel 7 viewport. Needs nothing running; CI runs it. First time locally: `npx playwright install chromium`.
- `npm run e2e:real`: the same app against a running API (`make api` + `make seed`). Reads `E2E_API_URL`
  (default `http://localhost:8000`) and `DEMO_PASSWORD` from the environment; it serves on :5174, which the
  API's CORS allows. These tests are read-only except "Merg eu", which writes only the audit log.
- `e2e/mock/` covers sign-in and `?next=`, sign-out, invites, the role matrix per page, the location switcher,
  "Merg eu" and the alert timeline, history filters, metrics. `e2e/real/` asserts each role loads its pages
  without any 4xx from the API (the anonymous `/api/auth/me` probe excepted).
- Failures keep a trace and screenshot in `test-results/`; open one with `npx playwright show-trace <zip>`.

### Screens (UI copy in Romanian)
| Route | Page | Purpose |
|---|---|---|
| `/` | Live | camera tiles, live video with detection boxes, alert feed, staff suggestions |
| `/camere/:cameraId/zone` | Zone editor | draw polygons on a live frame or an uploaded still; tags `table`, `entrance`, `staff` |
| `/reguli` | Reguli | write a rule in Romanian → "Ce am înțeles" draft → Confirmă / Modifică / Renunță |
| `/alerte` | Alerte | opened/closed alerts with blurred snapshot |
| `/dispozitive` | Dispozitive | edge devices online/offline, "Adaugă cameră" |
| `/metrici` | Metrici | FPS, CPU, verified ratio, events today, alert latency |

### Code map
`src/api/` client interface, `mock.ts`, `http.ts` · `src/contracts/` generated types (never edit) ·
`src/zones/geometry.ts` pure polygon logic · `src/alerts/fold.ts` · `src/rules/describe.ts` ·
`src/live/` WHEP player · `src/state/` shared state · `src/components/`, `src/pages/` · `src/styles.css`.

## API the frontend uses

Base `VITE_API_URL`. Errors: `{detail: {code, message_ro}}` — show `message_ro`.

| Method | Path | Notes |
|---|---|---|
| GET/POST | `/api/cameras` | POST accepts `id` (use `cam-01` for the demo); device comes from the API's `DEVICE` |
| GET | `/api/cameras/{id}` | includes `online` |
| GET/PUT | `/api/cameras/{id}/zones` | PUT replaces all zones |
| GET/POST | `/api/rules` · GET/PATCH/DELETE `/api/rules/{id}` | |
| POST | `/api/rules/from-text` | `{camera_id, text, save?}` → `{rule, explanation_ro, saved}`; may answer a clarifying question |
| GET | `/api/events?limit=` | AlertEvent + `device_id`, `snapshot_url` |
| GET | `/api/snapshots/{event_id}` | blurred JPEG |
| GET | `/api/devices` | status, `last_seen` |
| GET | `/api/staff/suggestions` · POST `.../{id}/confirm` · `.../{id}/reject` | |
| GET | `/api/staff/profiles` · POST `/api/staff/photos` | multipart field `photo` (images or a short video) |
| GET | `/api/metrics` | `DashboardMetrics`; `alert_latency_ms` may be `null` |
| GET | `/api/push/public-key` | VAPID key; 503 when the server has no keys |
| POST/DELETE | `/api/push/subscribe` | body = `PushSubscription.toJSON()` / `{endpoint}` |
| POST | `/api/push/test` | test push to every subscription → `{sent, removed, failed}` |
| WS | `/ws/events` | `{type: 'alert' \| 'suggestion', data}` and `{type: 'detections', camera_id, data: [{track_id, role, box: [x,y,w,h], staff_score, raised_hand}]}` |

Contract types: `packages/contracts` → `make schema` → `npm run contracts`. Don't hand-write API types.

## Design system

- One palette, from the logo. The source of truth is `docs/brand/tokens.css`, and the rules are in `docs/brand/README.md`.
  Its `:root` block is copied to the top of `src/styles.css`. Use only the variables, never raw hex values.
- The look is a light working surface (`--ground` `#F6F7F9`, `--surface` white, `--ink` `#14161B` text) with night
  chrome: the sidebar, camera media and the suggestion card are ink. Add `.on-night` to any dark container;
  it remaps `--text`, `--surface*`, `--border*` and `--focus`.
- Coral `#FF5C6C` means "needs attention" (open alerts, the one alert action). Use it for fills only. As text on
  light, use `--coral-strong` `#C8283E`. On camera media, light blue (`--live-on-night`) marks staff and live,
  and white/grey marks guests and tables.
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
- Push needs a secure context: `localhost` or HTTPS. On a phone, serve the dashboard and the API over HTTPS
  (e.g. `tailscale serve`) and add that origin to the API's `CORS_ORIGINS`.

## Still to build (frontend)
- Presentation site `apps/site` (static, GitHub Pages): problem, how it works, privacy, architecture, team, demo video.
- Pitch slides and demo video (see the demo script in the design doc).

## Known gaps
- WHEP live video checked only headless (black frame) — verify in a real browser.
- Snapshots return 404 when the API runs on the host (`make api`) while ingest writes into a Docker volume.
- Events from the fake edge use zone id `masa-1`; dashboard-created zones get `z-<ts>` ids.
