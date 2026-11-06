# Accounts, roles per location, audit history, alert lifecycle — spec

Agreed with the team on 2026-11-06 (decisions D19–D24). Three parallel streams build against this file:
**A** backend auth + tenancy + audit, **B** alert lifecycle, **C** dashboard UI. Change this file first
(PR into `develop`) if the contract below has to change.

## Model

```
Organization ─┬─ Location (= existing `sites` row; type: restaurant | terrace | event | shop | other)
              │     └─ devices · cameras · zones · rules · events · telegram_chat_id
              └─ Users ── Membership(location, role: manager | staff)
                           owner = flag on the user within the org → every location of the org
```

- A user belongs to one organization (multi-org is Won't).
- Location id is the MQTT `<site>` segment. The existing demo site `demo` becomes the demo location.
- Every existing resource (cameras, zones, rules, events, devices, suggestions, profiles) is scoped to a
  location through its site/device. Requests for another org's or another location's data return 404.

## Roles → permissions

| Permission | owner | manager | staff |
|---|:-:|:-:|:-:|
| `alerts.view` (live, alerts, metrics) | all locations | own | own |
| `alerts.ack` ("Merg eu", close) | ✓ | ✓ | ✓ |
| `staff.review` (confirm/reject suggestion) | ✓ | ✓ | – |
| `staff.enrol` (uniform photos) | ✓ | ✓ | – |
| `rules.manage` | ✓ | ✓ | – |
| `devices.manage` (cameras, zones, devices) | ✓ | ✓ | – |
| `users.manage` | ✓ | ✓ staff only, own location | – |
| `locations.manage` | ✓ | – | – |
| `audit.view` | all | own location | own actions only (`audit.view.own`) |

Permissions are enforced in the API (a `require(permission, location_id)` dependency). The UI only hides.

## Auth

- Passwords: argon2 (`argon2-cffi`). Min 8 chars.
- Session: opaque random token (32 bytes, urlsafe) stored hashed (sha256) in `sessions` with expiry 12 h,
  sliding. Sent as cookie `aivee_session`: `HttpOnly; SameSite=Lax; Path=/`; `Secure` when `COOKIE_SECURE=true`.
  localhost:5173 → localhost:8000 is same-site, so `fetch(..., {credentials: "include"})` works; CORS
  `allow_credentials=True` with explicit origins (`CORS_ORIGINS`, default `http://localhost:5173,http://localhost:5174`).
- `/ws/events` authenticates with the same cookie and only streams the user's locations.
- Rate limit login: 10 failed attempts per email per 15 min → 429 with Romanian message.
- Demo seed (`make seed`, idempotent): org "AiVee Demo", location `demo` ("Terasa demo", restaurant),
  users `owner@aivee.demo`, `manager@aivee.demo`, `staff@aivee.demo`; password from env `DEMO_PASSWORD`.

## Endpoints (stream A unless marked B)

Errors keep the existing shape `{detail: {code, message_ro}}`; 401 `unauthenticated`, 403 `forbidden`.

| Method | Path | Body → Response |
|---|---|---|
| POST | `/api/auth/register` | `{org_name, name, email, password}` → `Me` (creates org + owner, sets cookie) |
| POST | `/api/auth/login` | `{email, password}` → `Me` (sets cookie) |
| POST | `/api/auth/logout` | → 204 (clears cookie, deletes session) |
| GET | `/api/auth/me` | → `Me` |
| GET/POST | `/api/locations` | list visible / create `{id, name, type, telegram_chat_id?}` (`locations.manage`) |
| PATCH/DELETE | `/api/locations/{id}` | (`locations.manage`) |
| GET | `/api/locations/{id}/members` | → `[{user_id, name, email, role}]` (`users.manage`) |
| PATCH/DELETE | `/api/locations/{id}/members/{user_id}` | `{role}` (`users.manage`) |
| POST | `/api/invites` | `{location_id, role, email}` → `{invite_url, expires_at}` (`users.manage`; 7 days) |
| GET | `/api/invites/{token}` | → `{org_name, location_name, role, email}` (public) |
| POST | `/api/invites/{token}/accept` | `{name, password}` → `Me` (sets cookie) |
| GET | `/api/audit` | `?location_id&actor=&kind=&before=&limit=50` → `{items: [AuditEntry], next_before}` |
| POST | `/api/alerts/{event_id}/ack` | **B** → `AlertView` (`alerts.ack`; 409 if already acknowledged) |
| GET | `/api/alerts` | **B** `?location_id&state=&limit` → `[AlertView]` (one row per alert, folded) |
| GET | `/api/metrics/service` | **B** `?location_id&from&to` → wait / reaction / travel medians and p90 |

Existing endpoints gain an optional `location_id` query param (default: the user's first location) and are
filtered by membership.

```ts
type Role = "owner" | "manager" | "staff";
type Me = {
  user: { id: string; name: string; email: string };
  org: { id: string; name: string };
  is_owner: boolean;
  locations: { id: string; name: string; type: string; role: Role; permissions: string[] }[];
};
type AuditEntry = {
  id: string; at: string; location_id: string | null;
  actor: { kind: "user" | "device" | "system"; id: string; name: string };
  kind: string;            // e.g. "auth.login", "rule.updated", "alert.acknowledged"
  target: { type: string; id: string; label: string } | null;
  summary_ro: string;      // "Ana a preluat alerta de la Masa 4"
  before: unknown | null; after: unknown | null;
};
```

## Audit history

- Table `audit_log`, append-only: the DB role used by the API has no UPDATE/DELETE on it (revoke in the
  migration) and the repository exposes only `append` and `query`.
- Kinds: `auth.login`, `auth.login_failed`, `auth.logout`, `user.invited`, `user.joined`, `member.role_changed`,
  `member.removed`, `location.created|updated|deleted`, `camera.*`, `zones.updated`, `rule.created|updated|deleted`,
  `staff.confirmed|rejected|enrolled`, `alert.opened|acknowledged|arrived|closed` (B), `device.online|offline`.
- Config changes store `before` / `after` JSON. Every entry has a Romanian `summary_ro`.
- Ingest writes `alert.*` (actor = device) and `device.*`; the API writes the rest (actor = user).

## Alert lifecycle (stream B)

```
opened (edge) ──► acknowledged (user, "Merg eu") ──► arrived (edge: staff in the zone ≥ ARRIVE_S=5 s) ──► closed (edge)
                └─ arrived may come without acknowledged (recorded as "fără preluare")
```

- Contract: `AlertEvent.state` becomes `"opened" | "arrived" | "closed"` (edge-produced). `acknowledged` is a
  user action stored by the API (`alerts.acknowledged_by`, `acknowledged_at`), not an edge event.
- Edge: the engine emits `arrived` once per open alert when a `staff` track's foot point stays in the zone
  ≥ `ARRIVE_S`; walking past does not count.
- Folded view `AlertView`: `{event_id, rule_id, location_id, camera_id, zone_id, zone_name, summary_ro,
  opened_at, acknowledged_at, acknowledged_by, arrived_at, closed_at, wait_s, reaction_s, travel_s}`.
  - wait = arrived (or closed) − opened; reaction = acknowledged − opened; travel = arrived − acknowledged.
- Telegram message for an opened alert links to the dashboard alert; a second message on `arrived`
  ("Ana a ajuns la Masa 4 după 2 min 10 s").

## Dashboard (stream C)

- `/intra`, `/cont-nou`, `/invitatie/:token` on the API; `?next=` return.
- Location switcher in the sidebar (owner and multi-location users); everything reads the current location.
- `can(permission)` hides actions; pages: **Istoric** (`/istoric`, filters: actor, kind, period),
  **Echipă** (`/echipa`: members, roles, invite link), **Locații** (`/locatii`, owner).
- Alert card: "Merg eu" button (coral, the one accent action), then the timeline opened → preluată → ajuns → închisă
  with durations. Metrics page: wait / reaction / travel.
- `fetch` with `credentials: "include"`; 401 → `/intra?next=…`.
