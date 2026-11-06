# Frontend handbook — dashboard, PWA, site, design

## Dashboard (`apps/dashboard`)

- Stack: Vite 8, React 19, React Router, TypeScript strict, Vitest, ESLint + Prettier. No UI kit.
- Run against the mock: `npm ci && npm run dev` (no `VITE_API_URL`) — a 45 s demo timeline plays.
- Run against the real stack: `make up && make api` in the repo root, then
  `VITE_API_URL=http://localhost:8000 npm run dev`. Live video: `VITE_WHEP_BASE` (default `http://localhost:8889`).
- Checks before a PR: `npm run lint && npm test -- --run && npm run build`, and
  `npm run contracts && git diff --exit-code src/contracts`.

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
| WS | `/ws/events` | `{type: 'alert' \| 'suggestion' \| 'detections', data, camera_id?}` (`detections` arriving with the edge-commands PR) |

Contract types: `packages/contracts` → `make schema` → `npm run contracts`. Don't hand-write API types.

## Design system

- Tokens live at the top of `src/styles.css` (dark "night watch": ground `#0f1317`, accent amber `#f5a524`,
  live cyan `#4cc2e0`, danger `#f08a7e`, IBM Plex Sans / Mono, 44 px tap targets).
- Brand files: `docs/brand/` (logo, white logo, mark, app icon, favicon). The logo uses ink `#14161B` and coral
  `#FF5C6C` — **not yet reconciled** with the dashboard accent; the design session decides one palette and
  updates the tokens.
- Must work at 390 px (waiters use phones) and 1440 px (owner at a laptop). Alerts are glanceable: zone name,
  how long, one action.
- Privacy is visible: faces are blurred, staff confirmation is explicit ("Pare angajat — confirmi?").

## Still to build (frontend)
- PWA: manifest + service worker + web push for alerts (Should).
- Presentation site `apps/site` (static, GitHub Pages): problem, how it works, privacy, architecture, team, demo video.
- Pitch slides and demo video (see the demo script in the design doc).

## Known gaps
- WHEP live video checked only headless (black frame) — verify in a real browser.
- Snapshots return 404 when the API runs on the host (`make api`) while ingest writes into a Docker volume.
- Events from the fake edge use zone id `masa-1`; dashboard-created zones get `z-<ts>` ids.
