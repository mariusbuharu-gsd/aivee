# Decisions log

One line per decision. Newest last. Reopen a decision only with a new entry that says why.

| # | Date | Decision | Why |
|---|---|---|---|
| D1 | 11-05 | Domain: hospitality (restaurants, terraces, events). Problem: "people learn too late what happens in front of their cameras, because nobody has time to watch them." | Clear buyer, daily pain, easy live demo. |
| D2 | 11-06 | Four MVP events: unattended table, guest raises a hand, queue at the entrance, table not cleared. | All four come from one engine (present / absent / count / pose / objects + duration). |
| D3 | 11-06 | No smoke/fire, no bears, **no face recognition**. Faces are blurred before a snapshot leaves the device. | Privacy (GDPR), scope, trust. |
| D4 | 11-06 | Staff are recognised by **appearance** (CLIP embedding of uniform photos/video + text) **and behaviour** (moves more than guests, visits many tables), with owner confirmation. | Works without faces; the owner stays in control. |
| D5 | 11-06 | Rules are written in Romanian; Claude (`claude-opus-5-5`, structured outputs, effort low) turns them into a JSON `Rule`. The result is a **draft** the owner confirms or edits. | Non-technical owners; the model never acts on its own. |
| D6 | 11-06 | Everything heavy runs **on the edge** (CPU, OpenVINO INT8 YOLO11n + ByteTrack, pose only inside table zones, CLIP every 2 s per person). | Low bandwidth, no video leaves the site, cheap hardware. **Partly superseded by D25** (11-06): edge is now an option, not the default; the CPU pipeline itself stays. |
| D7 | 11-06 | **MQTT done properly**: Mosquitto with per-device ACL (`%u`), LWT, retained config/rules/profiles, QoS 1, shared subscriptions for ingest. **Postgres 17 + pgvector**, no SQLite. | Scalability and architecture criteria; real IoT patterns. |
| D8 | 11-06 | Edge state is **retained and complete**: the API publishes the full RuleSet / DeviceConfig / StaffProfiles on every change. The DB is the source of truth. | An edge that reboots gets everything at once; no diffs to reconcile. |
| D9 | 11-06 | `packages/contracts` (Pydantic) is the single source of truth → JSON Schema → TS types for the dashboard. CI fails on drift. | One definition shared by edge, API, ingest and UI. |
| D10 | 11-06 | Clean architecture on the edge: pure `domain/` (mypy strict, no IO) behind `Protocol` ports; adapters for YOLO, CLIP, MQTT, Postgres, Telegram, Claude. | Testable, swappable, "implementation quality" criterion. |
| D11 | 11-06 | GitHub + GitHub Actions (Node 24 actions), gitleaks in CI. Repo goes public Saturday ~09:00. | Hackathon requirement and visibility. |
| D12 | 11-06 | Alerts go to **Telegram** (group "AiveeAlerts", bot `@aivee_sibiu_bot`) for the MVP; PWA push is a Should. | Works today on every phone. |
| D13 | 11-06 | Demo camera: Android phone with IP Webcam (MJPEG `http://<ip>:8080/video`, 640x480). The stream arrives rotated → edge rotates 90° clockwise (`ROTATE=90`). | No extra hardware; YOLO confidence drops a lot on rotated frames. |
| D14 | 11-06 | Zones are drawn by hand in the dashboard on a still from the camera. No auto-detected table zones (YOLO doesn't find "dining table" top-down). | Reliable for the demo. |
| D15 | 11-06 | Default ids for the demo: site `demo`, device `edge-01`, camera `cam-01`. Rules and zones must use the same camera id the edge runs with. | Otherwise the edge has no zones and nothing fires. |
| D16 | 11-06 | Git flow: `feature/*`, `fix/*`, `docs/*` → PR into `develop` (default branch) → squash after green CI. `develop` → `main` only at milestones. | `main` is always demo-ready. |
| D17 | 11-06 | **No AI attribution** in commits or PRs. Code, docs, commits in English; UI copy in Romanian. | Team decision. |
| D18 | 11-06 | Dashboard: Vite + React 19 + strict TS, plain CSS with tokens ("night watch" dark theme), mock API when `VITE_API_URL` is unset. | Fast, no UI framework lock-in, demo works offline. |
| D19 | 11-06 | AiVee is for **locations** in general (restaurants, terraces, events, shops), not only restaurants. Organization → locations → devices. A location is the MQTT `<site>`. | Wider market; the engine is not restaurant-specific. |
| D20 | 11-06 | Real accounts: argon2 passwords, opaque session in an HttpOnly cookie, invites by link. | Secure by default without an identity provider. |
| D21 | 11-06 | Roles **per location**: manager, staff; owner sees every location of the org. Fixed permission matrix enforced in the API. | Matches how places are staffed; staff only get their location's alerts. |
| D22 | 11-06 | Append-only **audit history** of accounts, configuration (before/after), staff decisions, alerts and devices. | Accountability and service statistics. |
| D23 | 11-06 | Alert lifecycle opened → acknowledged ("Merg eu") → arrived (edge sees staff ≥ 5 s) → closed, with wait / reaction / travel times. | The owner's real question: how long do guests wait and how fast do we react. |
| D24 | 11-06 | Spec for D19–D23: `docs/plans/2026-11-06-auth-roles-audit.md`. | One contract for three parallel streams. |
| D25 | 11-06 | **Cloud-first standard offer.** One shared multi-tenant cloud: cameras stream to it, video is analysed in memory and discarded, never stored, servers in the EU. **Edge is an option**: on the customer's own PC or on our edge box, for maximum privacy or offline use. A dedicated server only on a custom Enterprise plan. The code stays MIT. Details: `docs/adr/0011-cloud-or-edge-analysis.md`. | Removes the hardware barrier: a location starts with the cameras it already has. Edge stays for venues that want video to never leave or need to work offline. |
| D26 | 11-06 | **Licensing.** Our own code stays MIT. The detector, Ultralytics YOLO, is AGPL-3.0 (verified on `ultralytics` 8.4.203, the version in `uv.lock`). Running it in our cloud or distributing it (edge box, customer PC) must comply with AGPL-3.0: the complete source of what runs, including our changes, available to its users. Otherwise an Ultralytics Enterprise licence. | AGPL covers network use, so cloud mode does not escape it; open code (Q26) makes compliance straightforward. |
