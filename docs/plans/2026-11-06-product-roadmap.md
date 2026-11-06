# AiVee product roadmap — implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or subagent-driven-development) to implement this plan task by task. Every code task follows superpowers:test-driven-development and the rules in `CLAUDE.md`.

**Goal:** Turn the decisions in `docs/backlog/ideas.md` (Q1–Q39, I1–I4) and the review findings (A, C, M) into shipped work, without breaking the demo.

**Architecture:** One multi-tenant cloud (organisation → company → brand → location). Video is analysed either in our cloud (standard) or on site (edge on the customer's PC, or our edge box, paid extra). The vision pipeline stays one codebase behind `typing.Protocol` ports, so the same domain code runs on site and as a cloud worker. Code stays open source (MIT).

**Tech stack:** Python 3.12 uv workspace (FastAPI API, aiomqtt ingest, OpenVINO edge), Pydantic contracts in `packages/contracts`, Postgres + pgvector, Mosquitto, MediaMTX, React dashboard/PWA, static site.

---

## How to use this plan (orchestrator)

- **One task = one branch = one PR** to `develop` (`feature/<slug>`, `fix/<slug>`, `docs/<slug>`). Squash merge after green CI.
- Each task lists the **folders it owns**. Never give two running sessions tasks that own the same folder.
- **Contract changes** (`packages/contracts`) are marked **[contract]**. Run at most one [contract] task at a time; it bumps `schema_version` (task P2.1 introduces it) and runs `make schema`.
- Each executing session writes its own bite-sized TDD steps for its task (failing test → minimal code → green → commit). Done means: `make test` and `make lint` pass, plus `make test-all` when the task touches DB, MQTT or ingest.
- Task cards give: backlog references, owned folders, what to build, the tests that prove it, and dependencies.
- **Hackathon guard.** Before the 00:00 feature freeze, run only **Phase 0** tasks. They are small, don't touch contracts, and don't change the demo path. Between 00:00 and the Saturday 10:30 code freeze, only fixes go in. Phases 1–7 start after the code freeze; `main` stays the demo tag `v1.0`.
- **Not code (owner actions)** are listed at the end. They block some tasks.

Already done on `develop` (don't redo): alert lifecycle opened → acknowledged → arrived → closed with ≥ 5 s arrival (#21, D23); accounts, roles per location, audit (#19, #23); alerts of offline devices close (#28, covers part of E8/E11).

---

## Phase 0 — before the 00:00 freeze (demo-safe)

### P0.1 ADR 0011: cloud or edge, per customer
- **Refs:** I4, Q12, Q31–Q35. Supersedes part of ADR 0001.
- **Owns:** `docs/adr/0011-cloud-or-edge-analysis.md`, `docs/adr/0001-*.md` (status line only), `docs/decisions.md` (one new row).
- **Build:** context (hardware barrier), decision (three modes: Cloud standard, Edge on the customer's PC, Edge box; one shared multi-tenant cloud; dedicated server only on Enterprise), consequences (privacy message per mode, AGPL obligations of Ultralytics in cloud mode (Q37), offline behaviour per mode).
- **Done when:** ADR 0001 says "Status: partly superseded by ADR 0011"; decisions log row added.

### P0.2 Site: buyer message, CTA, honest privacy, team
- **Refs:** M1, M2, M3, M5, M6, M12, M16, Q24, Q26.
- **Owns:** `apps/site/src/`.
- **Build:**
  1. Hero (`index.html:54`): pain in money terms for independent table-service restaurants (Q24); no unsourced statistics.
  2. Replace "Codul pe GitHub" primary CTA (`index.html:63`) with "Vreau un pilot" linking to a contact section showing a phone number and an e-mail as selectable text with a copy button (no `mailto:` reliance). Keep GitHub in the footer (code stays open).
  3. Privacy section (`#confidentialitate`): two short columns, "Cloud" and "Edge", with the exact claims from ADR 0011. Cloud: "video-ul e analizat și aruncat, nu e salvat niciodată, servere în UE". Edge: "video-ul nu pleacă din restaurant".
  4. New "Pentru echipa ta" block: team-level statistics only, no ranking of waiters (Q1).
  5. Move "Arhitectură" lower and label it for the technical reader (M3).
  6. Team section: fill roles, remove "Rol: de completat" (M16).
- **Tests:** existing site checks if any; manual check at 400 px and in dark mode.
- **Depends:** P0.1 (wording of privacy claims).

### P0.3 One vocabulary in the dashboard
- **Refs:** M14, I2.
- **Owns:** `apps/dashboard/src/` copy only (no logic).
- **Build:** pick one term ("masă neservită" vs "masă uitată") and one definition of "așteptare" (from the guest sitting down; "reacție" = alert → "Merg eu"; "drum" = "Merg eu" → arrival). Replace everywhere; add the definitions as help text on the metrics page.
- **Tests:** dashboard unit tests and Playwright mock e2e still green (`apps/dashboard/e2e/mock`).

### P0.4 Re-alert the shift 2 min after an unfulfilled acknowledgement
- **Refs:** Q2, E1, Q5.
- **Owns:** `apps/ingest/src/aivee_ingest/` (a periodic check) and `apps/api/src/aivee_api/alerts/` (query only).
- **Build:** a loop in ingest that finds alerts with `acknowledged_at` older than 2 min, `arrived_at` null, not closed, not yet re-alerted. It notifies the whole location again ("Masa 4: Ana a confirmat acum 2 min, încă nu a ajuns nimeni") and records `realerted_at` in a migration. The delay is a setting (`REALERT_AFTER_S=120`).
- **Tests:** unit: an alert acknowledged 121 s ago is selected once; one at 119 s is not; an arrived alert is not. Integration (testcontainers): the notifier fake is called once.
- **Check Q5 first:** confirm acknowledgement already stops the alarm on all phones and shows who goes; if not, include it here.
- **Hackathon note:** run only if P0.1–P0.3 are merged and there is time before 00:00; otherwise it becomes P3.2.

---

## Phase 1 — multi-tenant foundation (after the code freeze)

Order matters: P1.1 → P1.2 → (P1.3, P1.4 in parallel) → P1.5 → P1.6.

### P1.1 Tenancy model: company and brand [migration]
- **Refs:** Q13, C1, E15.
- **Owns:** `apps/api/src/aivee_api/accounts/`, `apps/api/src/aivee_api/locations/`, `apps/api/alembic/versions/`.
- **Build:** tables `companies` (org_id, legal name, CUI, billing address) and `brands` (company_id, name). `sites.brand_id` not null. The migration creates one default company and brand per existing organisation and attaches every location. The API hides company and brand when an org has exactly one of each.
- **Tests:** migration up/down on a seeded DB; a new org gets a default company + brand; listing locations works unchanged for a single-restaurant org; permission tests unchanged.

### P1.2 Surrogate ids per tenant [migration] [contract]
- **Refs:** A3.
- **Owns:** `apps/api/src/aivee_api/db/`, `apps/api/alembic/versions/`, `packages/contracts/`.
- **Build:** UUID primary keys for sites, devices, cameras, rules; user-chosen slugs become labels unique per organisation. MQTT topics use the UUIDs (`Topics` in contracts). Conflict messages never mention other organisations.
- **Tests:** two orgs can both create `cam-01`; topic builders produce UUID topics; existing fixtures migrated.

### P1.3 Edge sync for every location
- **Refs:** A1.
- **Owns:** `apps/api/src/aivee_api/edge/`, `apps/api/src/aivee_api/cameras/`, `apps/api/src/aivee_api/main.py`.
- **Build:** replace the single `SITE`/`DEVICE` binding (`main.py:55`, `edge/sync.py:36-47`) with per-location publishing: rules, config and profiles are published to the devices of the location they belong to. Cameras can be added to any location that has a paired device (`cameras/router.py:46-49`).
- **Tests:** integration: two locations, two devices; a rule on location 2 reaches only device 2.

### P1.4 Staff profiles per brand
- **Refs:** A2, Q14.
- **Owns:** `apps/api/src/aivee_api/staff/`, `apps/api/src/aivee_api/db/repositories.py`.
- **Build:** `staff_profiles.brand_id`; `profiles()` filtered by brand (`repositories.py:291`); devices receive only their location's brand profiles; enrolment picks the location's brand instead of `default_profile_id`.
- **Tests:** a manager of brand A cannot list brand B profiles; device of a brand-B location receives only brand-B centroids.

### P1.5 Device pairing and per-device MQTT credentials
- **Refs:** A4, A5, Q19.
- **Owns:** `apps/api/src/aivee_api/devices/`, `infra/mosquitto/`, `apps/edge/src/aivee_edge/adapters/` (credential loading), `apps/ingest/src/aivee_ingest/locations.py`.
- **Build:** "Adaugă device" creates a one-time pairing code (10 min). The edge exchanges it for its own credential. Mosquitto uses dynamic security (or an auth plugin backed by Postgres) with an ACL per device restricted to its own topics. Ingest no longer creates sites from unknown topics; events from unpaired devices are dropped and logged. Revoke and rotate from the Devices page.
- **Tests:** integration: an unpaired device's events are rejected; a paired device cannot publish under another site; revoked credential disconnects.

### P1.6 Transport security: MQTT TLS, MediaMTX auth
- **Refs:** A6.
- **Owns:** `infra/mosquitto/`, `infra/mediamtx/`, `apps/api/src/aivee_api/auth/` (stream token endpoint), `apps/dashboard/src/live/` (send the token).
- **Build:** Mosquitto TLS on 8883 only in non-dev profiles; MediaMTX auth via short-lived tokens issued by the API for users with access to that location.
- **Tests:** integration: plain connection refused in the TLS profile; WHEP without token gets 401; with a token for another location gets 403.

### P1.7 People across locations, offboarding, invites
- **Refs:** C3, C4, C5, Q1.
- **Owns:** `apps/api/src/aivee_api/accounts/`, `apps/api/src/aivee_api/auth/`, `apps/dashboard/src/pages/TeamPage.tsx`.
- **Build:** inviting an existing e-mail in the same org adds a membership instead of 409 (`invites.py:382`); a person screen with all their location roles; "Dezactivează" revokes all sessions and push subscriptions and writes an audit entry; pending invites list with revoke.
- **Tests:** existing user invited to a second location gets a second membership; deactivated user's session returns 401 on the next request.

### P1.8 Owner roles above location
- **Refs:** C2.
- **Owns:** `apps/api/src/aivee_api/auth/permissions.py`, `apps/api/src/aivee_api/accounts/`.
- **Build:** roles `co_owner`, `finance` (read-only + invoices), `area_manager` (manager over a set of locations, across companies). Update the fixed matrix and ADR 0008.
- **Tests:** permission matrix table tests for every role × action.

---

## Phase 2 — reliability

### P2.1 Contract versioning [contract]
- **Refs:** Q18.
- **Owns:** `packages/contracts/`, `apps/ingest/src/aivee_ingest/handler.py`.
- **Build:** `schema_version` on every MQTT payload; ingest accepts the current and previous version and logs others.
- **Tests:** a v(n-1) payload is accepted; v(n-2) is rejected with a log line.

### P2.2 `alert_id` and order-independent lifecycle [contract]
- **Refs:** A9.
- **Owns:** `packages/contracts/src/aivee_contracts/events.py`, `apps/edge/src/aivee_edge/domain/engine.py`, `apps/api/src/aivee_api/alerts/repository.py`, `apps/ingest/`.
- **Build:** the edge mints `alert_id` on open and repeats it on arrived/closed; ingest upserts by `alert_id`, so `closed` before `opened` still produces a correct row.
- **Tests:** events applied in every permutation give the same final row.

### P2.3 Durable delivery: edge outbox and durable ingest session
- **Refs:** A7, E8, E13.
- **Owns:** `apps/edge/src/aivee_edge/adapters/` (SQLite outbox), `apps/ingest/src/aivee_ingest/worker.py`.
- **Build:** edge writes events to SQLite before publishing and deletes on PUBACK; replays on reconnect. Ingest uses a persistent session. Events older than `MAX_NOTIFY_AGE_S` are stored but not notified (E13).
- **Tests:** kill the broker, emit 3 events, restart: all 3 arrive once; a 2 h old replayed event sends no Telegram.

### P2.4 Notification outbox
- **Refs:** A8.
- **Owns:** `apps/ingest/src/aivee_ingest/handler.py`, `notify.py`, migration.
- **Build:** a `notifications` row in the same transaction as the event; a sender loop with retry and backoff.
- **Tests:** a notifier that fails twice then succeeds sends exactly once; a crash between commit and send still sends after restart.

### P2.5 Camera health and config drift
- **Refs:** A12, E11.
- **Owns:** `packages/contracts/` [contract], `apps/edge/src/aivee_edge/adapters/capture.py`, `apps/api/src/aivee_api/devices/`, `apps/dashboard/src/pages/DevicesPage.tsx`.
- **Build:** status carries per-camera last-frame age, FPS and config hash. A camera without frames for 60 s raises a "Camera offline" alert; open alerts on that camera are marked "necunoscut" and excluded from statistics.
- **Tests:** domain test with a fake clock; dashboard shows the camera state.

### P2.6 Clock provenance
- **Refs:** A10.
- **Owns:** `packages/contracts/` [contract], `apps/ingest/`, `apps/api/src/aivee_api/alerts/`.
- **Build:** store `received_at`; status reports clock offset; flag skew > 2 s and use server time for reaction/travel when skewed.
- **Tests:** a 10 s skewed edge produces corrected durations and a flag.

### P2.7 Edge correctness fixes
- **Refs:** E9, E10, E12.
- **Owns:** `apps/edge/src/aivee_edge/domain/`, `apps/edge/src/aivee_edge/pipeline.py`.
- **Build:** `confirm_staff` validated against suggestions the edge issued (`pipeline.py:206`); closes caused by zone/rule edits carry reason `config_changed` and are excluded from stats; one zone per table across cameras (document; de-duplicate by table tag at location level in ingest).
- **Tests:** domain tests for each case.

### P2.8 Observability
- **Refs:** A13.
- **Owns:** `apps/api/src/aivee_api/main.py`, `apps/ingest/`, `infra/`.
- **Build:** real `/healthz` (DB + broker), Prometheus metrics (ingest lag, notifier failures, WebSocket clients). Wire alerts with the `gsd-alerts` skill.
- **Tests:** `/healthz` returns 503 when DB is down.

---

## Phase 3 — alerting and escalation

### P3.1 Severity and escalation [contract]
- **Refs:** I3, Q7, Q8, Q9, Q11.
- **Owns:** `packages/contracts/src/aivee_contracts/rules.py`, `apps/api/src/aivee_api/rules/`, `apps/ingest/src/aivee_ingest/notify.py`, `apps/dashboard/src/pages/RulesPage.tsx`.
- **Build:** `Rule.severity` (`info` | `normal` | `urgent`) with defaults per situation type, editable by the owner. Escalation policy: message at open; if no acknowledgement after `escalate_after_s`, call the location manager; if unanswered, call the owner. Calls only inside opening hours (P3.3). Replace or honour the ignored `Rule.action` (A-s3).
- **Tests:** policy is a pure function `next_step(alert, now, hours) -> Step`, fully unit tested.

### P3.2 Re-alert after an unfulfilled acknowledgement
- Only if P0.4 did not ship. Same card as P0.4.

### P3.3 Opening hours, holidays, time zone per location [migration]
- **Refs:** Q20, C9, Q11.
- **Owns:** `apps/api/src/aivee_api/locations/`, `apps/ingest/`, `apps/dashboard/src/pages/LocationsPage.tsx`.
- **Build:** weekly hours + exceptions per location; Romanian public holidays prefilled each year; time zone per location (replace hard-coded `Europe/Bucharest`, `notify.py:13`). Alerts outside hours are stored, not notified.
- **Tests:** an alert at 02:00 on a closed day is not notified; DST boundary test.

### P3.4 Voice calls
- **Refs:** Q10, E5, E6.
- **Owns:** `apps/ingest/src/aivee_ingest/` (new `voice.py` behind a port).
- **Build:** a `VoiceCaller` port with a Twilio-like adapter; Romanian text-to-speech message ("Masa 4 de la Pizzeria Roma așteaptă de 10 minute"); rate limit per location and one summary call when several urgent alerts are open.
- **Tests:** fake caller: 3 urgent alerts within a minute produce one summary call.
- **Blocked by:** owner action O3 (provider account).

### P3.5 "Sunt în tură" and owner digest
- **Refs:** Q21, Q39, Q6, C10.
- **Owns:** `apps/api/src/aivee_api/push/`, `apps/dashboard/src/pwa/`, `apps/dashboard/src/push/`.
- **Build:** a shift toggle per person and location; pushes go only to people on shift (fallback: all staff if nobody is on shift). Owners get a digest instead of every alert, except escalated calls. The on-shift count feeds the staffing metric, with the camera count as cross-check.
- **Tests:** owner receives no per-alert push; a staff member off shift receives none.

### P3.6 Local alarm for edge mode
- **Refs:** Q17, E7.
- **Owns:** `apps/edge/src/aivee_edge/adapters/` (new local alarm adapter).
- **Build:** the edge serves a small local page (tablet in the room) that sounds and lists open alerts when the internet is down.
- **Tests:** adapter test with the broker unreachable.

---

## Phase 4 — owner features

| Task | Refs | Owns | Build | Proof |
|---|---|---|---|---|
| P4.1 All-locations view | C7 | `apps/dashboard/src/pages/`, `apps/api/src/aivee_api/alerts/` | One screen: open alerts per location, longest wait, device health. | e2e mock test with 3 locations |
| P4.2 Linked rule templates with local overrides | C6, Q23, Q36, E16 | `apps/api/src/aivee_api/rules/`, migration, `RulesPage.tsx` | Brand-level template; locations inherit; per-field override; copy refused when a zone tag is missing. | unit: edit propagates except overridden fields |
| P4.3 League table (owners and group roles) | C8, Q23 | `apps/api/src/aivee_api/metrics/`, `MetricsPage.tsx` | Median wait and share of tables over threshold per location. | permission test: manager gets 403 |
| P4.4 Weekly report | C11, M | `apps/ingest/` or a new scheduler | Monday summary by e-mail/Telegram: worst hour, slowest zone, trend. Needs SMTP (O4). | snapshot test of the rendered report |
| P4.5 CSV export | C12 | `apps/api/src/aivee_api/audit/`, `alerts/` | Export alerts and history per period and location. | content test |
| P4.6 Archive or sell a location | C14, Q22, E14 | `apps/api/src/aivee_api/locations/` | Soft delete with restore period; archive keeps history with the seller; export bundle. | delete → restore round trip |

---

## Phase 5 — cloud mode and edge packaging

| Task | Refs | Owns | Build | Proof |
|---|---|---|---|---|
| P5.1 Stream connector | Q31 | new `apps/connector/` | Small program for any PC/router: pulls RTSP locally, pushes 640×360 at 5 fps over SRT/RTMP with TLS to our ingest. Cameras that can push do so directly. | integration with MediaMTX |
| P5.2 Cloud vision worker | I4 | new `apps/vision-worker/` reusing `apps/edge/src/aivee_edge/domain/` | One worker per camera stream; same domain code, adapters for cloud input and output. Frames kept in memory only (Q34). | same golden test clips give the same events as edge |
| P5.3 Bandwidth check | Q32 | `apps/connector/` | Measure upload on install; recommend edge below 5 Mbps. | unit on the decision |
| P5.4 Cost meter | Q33 | `apps/vision-worker/`, metrics | CPU/GPU seconds per camera per day, for pricing. | metric exported |
| P5.5 Offline state in cloud mode | Q35 | `apps/api/src/aivee_api/devices/`, dashboard | "Locație offline" when the stream stops; SMS-free in v1. | e2e mock |
| P5.6 Edge packaging and OTA | A11, Q15 | `apps/edge/`, new `infra/edge/` | Edge image; real version; models pinned with sha256 (`tools/download_models.py`); multi-camera per device; installer for the customer's PC; staged rollout channel. | CI builds the image; hash mismatch refuses to start |
| P5.7 AGPL compliance | Q37 | `docs/`, `README.md` | Verify the Ultralytics licence; publish the source of what runs in the cloud; licence notice in the app. | review |

---

## Phase 6 — data and GDPR

| Task | Refs | Owns | Build | Proof |
|---|---|---|---|---|
| P6.1 Retention jobs | Q16, A14 | `apps/ingest/` or scheduler, migration | Snapshots 7 days, events 12 months, audit 24 months; per-org settings later. | purge test with a fake clock |
| P6.2 Pseudonymised audit actors | Q16, A14 | `apps/api/src/aivee_api/audit/` | Audit stores actor ids; names resolved at read time; erasure removes the name mapping. | erased user shows as "Utilizator șters" |
| P6.3 Snapshots in object storage | A-s1 | `apps/ingest/`, `apps/api/`, `docker-compose.yml` | S3-compatible store, signed URLs. | integration with MinIO container |
| P6.4 Legal pack in the product | M4, Q16, Q34 | `apps/site/`, `docs/legal/` | Staff notice, camera sign, "what we don't store", DPA template, DPIA summary. Drafts only until O1. | review |

---

## Phase 7 — commercial

| Task | Refs | Owns | Build | Proof |
|---|---|---|---|---|
| P7.1 Plans and limits | Q25, M8 | `apps/api/`, migration | Plans Start/Sală/Lanț/Enterprise with camera limits per location; add-ons Edge PC and Edge box. | limit enforced on camera create |
| P7.2 Billing per company | C13, Q13 | `apps/api/` | Invoices per company; provider chosen in O5. | later |
| P7.3 Pricing page and pilot offer | M2, M8, M10 | `apps/site/` | Plans table, comparison with call buttons/POS timers/mystery shoppers. | review |
| P7.4 Silent mode for pilots | M7, Q29 | `apps/api/`, `apps/ingest/` | A location flag: measure, store, don't notify; pilot report before/after with median wait and share over threshold. | silent location sends nothing |
| P7.5 Onboarding: time to first alert | M9 | `apps/dashboard/` | Guided setup without RTSP jargon; measure time from register to first alert. | e2e |
| P7.6 English UI | Q28 | `apps/dashboard/`, `apps/site/` | i18n with Romanian and English only. | both locales render |
| P7.7 Manual rule editor | Q27 | `apps/dashboard/src/rules/` | Build a rule without the LLM. | e2e |

Smaller technical items to schedule when their area is touched: WebSocket via `LISTEN/NOTIFY` (A-s2, `events/router.py:101-106`), CI builds images and deploys (A-s4).

---

## Owner actions (not code)

| # | Action | Blocks |
|---|---|---|
| O1 | Lawyer review: DPIA, DPA, staff notice, Law 190/2018 art. 5, cloud video processing | P6.4, cloud launch |
| O2 | Trademark search (OSIM/EUIPO) and .ro domain for AiVee | site launch |
| O3 | Voice-call provider account (Twilio-like) and a Romanian sender number | P3.4 |
| O4 | Transactional e-mail provider (SMTP) | P1.7 invites by mail, P4.4 |
| O5 | Billing provider and company invoicing setup | P7.2 |
| O6 | Pick the reference edge hardware; measure cameras per box | P5.6 |
| O7 | Recruit 2–3 independent restaurants in Sibiu for the pilot; agree the success metric up front | P7.4 |
| O8 | Agree the licence position with all three authors; confirm the hackathon rules | P5.7 |
