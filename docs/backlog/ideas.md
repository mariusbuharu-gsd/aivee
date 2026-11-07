# AiVee — ideas, edge cases, open questions

A parking lot. Nothing here is scheduled. An item moves to the implementation plan
only when we explicitly decide "we build this now".

Status: `open` (just noted) · `clarified` (we agree what it means) · `approved` (go) · `done` · `dropped`
Priority (from the 2026-11-06 review): **P0** must before a pilot · **P1** should · **P2** later

## Ideas

| # | Idea | Why | Status | Notes |
|---|------|-----|--------|-------|
| I1 | **Alert lifecycle after the alarm**: opened → acknowledged ("Merg eu") → arrived (staff at the table ≥ 5 s) → closed. | Stopping the alarm does not resolve the case; arriving at the table does. | done | Built in #19 (D23, `apps/api/.../alerts/domain.py`). Event ordering is fragile, see A9. |
| I2 | **Service statistics on top of I1**: total wait, reaction time, travel time, staffing pressure per hour, shift, zone. | "How long do guests wait, do I have enough waiters, how fast do we really get there?" | partly done | Wait, reaction and travel times exist (`ServiceStats.tsx`). Staffing pressure (d) is still open, see Q6. Naming conflict: see M14. |
| I3 | **Alert severity decides the channel**: `info` → dashboard, `normal` → message, `urgent` → phone call. | Minor issues need a message; important ones must reach someone. | open | Rule has one `action` (`telegram`/`push`/`webhook`) and ingest ignores it anyway (A-s3). Q7–Q11. |
| I4 | **Cloud mode without on-site hardware; edge as a paid option.** Cameras send a low-resolution stream (e.g. 640×360, 5 fps) to our cloud, where the same vision pipeline runs per camera. The on-site edge box becomes a premium option (privacy, works offline); a third option runs the edge software on the customer's own PC. | Removes the hardware barrier and our dependence on shipping boxes; lets a restaurant start in a day. | decided | Three modes: Cloud (standard, nothing on site but cameras), Edge on the customer's PC, Edge box (paid extra). Contradicts ADR 0001 and the "video never leaves the site" claim, so it needs a new ADR and a privacy message per mode. Q31–Q35 decided. |
| I5 | **Ask the camera in Romanian** ("când a venit curierul?", "au fost pahare roșii pe masă?"). Index ~1 frame/s as CLIP embeddings + a blurred thumbnail and time; search by text embedding; confirm the top 3–5 hits with the vision model. | Turns the cameras into a searchable log, not only fixed rules. CLIP is already in the edge. | partly done | **Live part done** (`feature/open-rules`): open rules — `object_present` (any COCO class) and `visual` (zero-shot CLIP prompts) alert on what the owner asks for in Romanian; see backend handbook „Reguli libere”. Still open: the searchable index of past frames. P2. Cheap: indexing and search run locally, only confirmations cost. Works for colours, clothes, big objects; "curier" must be described ("om cu cutie de livrare la intrare"); small objects at 3 m don't. Privacy: contradicts "analizat și aruncat" — keep only embeddings + blurred thumbnails, a few days' retention, update the consent text. Builds on I6. |
| I6 | **AI verification of every alert**: before notifying, send the alert's snapshot (before/after for `object_gone`) and the rule's own Romanian text to a vision model → confirmed / rejected + a one-line Romanian description. Store every result to measure the false-alarm rate per rule. | Fewer false alarms, a human-readable reason, and data on which rules need tuning. | in progress | `feature/object-change` (object disappeared from a table + generic verifier, flag `VERIFY_ALERTS`). One call per alert, timeout, unavailable → normal alert. |
| I7 | **Upload a recorded video** and get a timeline of events (time in the clip, blurred snapshots, click to jump). | Lets a prospect try AiVee on their own footage without installing anything. | open | P1 after the freeze. The pipeline already runs on files (`make edge SOURCE=clip.mp4`); needs an upload endpoint, an offline runner (as fast as the CPU allows) and a timeline page. |

## Review 2026-11-06 — architect / developer

| # | Idea | Why | Prio | Evidence |
|---|------|-----|------|----------|
| A1 | **Edge sync serves every location**, not one `SITE` from env. | #19 made locations multi-site, but rules, config and profiles reach only one site's edges; cameras for location 2 are refused. | P0 | `api/main.py:55`, `edge/sync.py:36-47`, `cameras/router.py:46-49` |
| A2 | **Scope staff profiles** per location/brand/org. | All profiles go to every device and every manager; uniforms get averaged into one centroid. | P0 | `db/repositories.py:291`, `staff/router.py:85,108`, `db/models.py:619` |
| A3 | **Ids unique per tenant** (surrogate UUIDs, slugs as labels). | Two orgs cannot both have `cam-01`; the error leaks that another org uses it. | P0 | `db/models.py:40,62,75,85` |
| A4 | **Device pairing instead of first claim**; ACL bound per device. | Ingest auto-creates a site for any topic; any owner can claim it and get that edge's alerts. Any edge can publish under any site. | P0 | `locations/service.py:56,164-170`, `infra/mosquitto/acl` |
| A5 | **Device provisioning**: one-time pairing token → per-device credential, rotate and revoke. | The broker has exactly one edge user. | P0 | `infra/mosquitto/entrypoint.sh` |
| A6 | **TLS on MQTT, auth on MediaMTX**. | Plain 1883; MediaMTX lets anyone publish/watch raw unblurred video, which breaks "video never leaves the site". | P0 | `mosquitto.conf`, `mediamtx.yml` |
| A7 | **Lossless event delivery**: durable ingest session + on-disk outbox on the edge. | Events are dropped while workers are down or the edge reboots offline. | P0 | `ingest/worker.py:203-210` |
| A8 | **Notification outbox** with retry, written in the same transaction. | A crash between commit and send means the alert is never sent (redelivery is skipped as duplicate). | P0 | `ingest/handler.py:85-107` |
| A9 | **`alert_id` in `AlertEvent`**; order-independent lifecycle updates. | `closed` processed before `opened` leaves an alert open forever. Contract change + version bump. | P0 | `alerts/repository.py:84-115` |
| A10 | **Clock sync and time provenance** (NTP, offset in status, `received_at`). | Edge times and server times are mixed; skew corrupts reaction/travel stats. | P1 | `app.py:37-39` |
| A11 | **Edge packaging and OTA**: image, real version, pinned models with sha256, staged rollout, supervisor. | No edge image, version hard-coded, models from unpinned URLs. | P0 | `mqtt.py:57`, `tools/download_models.py:18` |
| A12 | **Camera health in status** (last-frame age, FPS, config hash) + "camera down" alert. | A frozen camera shows as "online" while nothing is watched. | P0 | `capture.py:86-108` |
| A13 | **Observability**: Prometheus metrics, real `/healthz`, alerts on ingest lag and notifier failures. | Today nothing tells us the system is degraded. | P1 | `main.py:121-123` |
| A14 | **Retention and GDPR**: purge jobs, per-org retention, pseudonymised audit actors, processor terms (Telegram, Claude). | Nothing is ever deleted; immutable audit stores names (erasure conflict). | P0 for paid pilot | `0003_auth_tenancy.py:173` |
| A-s1 | Snapshots in object storage, not a host bind mount. | Needed for multi-host. | P1 | `docker-compose.yml` |
| A-s2 | WebSocket via `LISTEN/NOTIFY` or broker, not polling. | ~3 queries/s per open phone. | P1 | `events/router.py:101-106` |
| A-s3 | Honour `Rule.action` (or remove it); guard webhooks against SSRF. | The LLM picks an action that ingest ignores. | P1 | `ingest/notify.py` |
| A-s4 | CI builds images and has a deploy job. | | P1 | `ci.yml` |

## Review 2026-11-06 — owner of several companies

| # | Idea | Job it serves | Prio | Evidence |
|---|------|---------------|------|----------|
| C1 | **Company / brand level** under the organisation. | Billing per company, grouping, brand managers. | P0 if billing per company | absent; `accounts/models.py:15-62` |
| C2 | **More owners / org-wide roles** (co-owner, finance read-only, area manager). | Finance, group operations, handover. | P1 | `permissions.py:173` |
| C3 | **Add an existing person to a second location from the UI.** | A waiter who works two locations; today the invite returns 409. | P0 | `invites.py:382`, `TeamPage.tsx` |
| C4 | **Pending invites**: list, revoke, send by email. | Links are copied by hand; no SMTP. | P1 | `TeamPage.tsx:177` |
| C5 | **Full offboarding**: deactivate, revoke sessions, audit entry. | Removed staff keep a valid session up to 12 h. | P0 | `principal.py:263` |
| C6 | **Copy a rule set to other locations** (map by zone tag, refuse when zones are missing). | Same brand, same rules. | P1 | `rules/router.py:46-106` |
| C7 | **All-locations view** for the owner (quiet summary: "3 open, longest 9 min at X"). | The phone at 23:00 with 12 locations. | P0 | `LiveData.tsx:22-34` |
| C8 | **League table** of locations by wait time. | Which location makes guests wait. | P1 | `MetricsPage.tsx` |
| C9 | **Opening hours, holidays, time zone per location**; alerts off when closed. | Cleaners trigger alerts at night; TZ hard-coded. | P0 | `rules.py`, `ingest/notify.py:13` |
| C10 | **Recipients per shift; owners opt for digests**. | Every owner gets every push from every location. | P0 | `push/repository.py:63-71` |
| C11 | **Weekly report** by email/Telegram (worst hour, slowest zone, trend). | Owners don't open dashboards; this keeps them paying. | P1 | absent (also marketing) |
| C12 | **CSV export** of alerts and history. | Audits, accountants, own BI. | P1 | `audit/router.py:85-96` |
| C13 | **Billing, plans, invoices** (per company). | | P2 | absent; depends on C1 |
| C14 | **Selling a location**: transfer or archive, soft delete with restore. | Delete cascades today; history loses its scope. | P1 | `models.py:557` |

## Review 2026-11-06 — marketing

| # | Idea | Why it sells | Prio | Evidence |
|---|------|--------------|------|----------|
| M1 | **Value in lei, not technology** on the hero. | Owners buy lost covers, tips, reviews. | P0 | `apps/site/src/index.html` |
| M2 | **Real CTA + pilot offer** ("pilot gratuit 14 zile", form or phone). | Today the only CTAs are "Cum funcționează" and GitHub. | P0 | `index.html` |
| M3 | **Separate buyer and jury versions** of the site (tech on `/tehnic`). | MQTT/pgvector is for the jury, not the buyer. | P0 | `index.html` |
| M4 | **GDPR / staff-monitoring pack**: staff notice, DPIA summary, camera sign, "what we don't store". | Biggest objection; Law 190/2018 art. 5 (to verify). | P0 | only `RegisterPage.tsx:117` |
| M5 | **Privacy claims match reality** ("video doesn't leave; the alert with a blurred photo does"). | Snapshots go to Telegram, rules to Claude, WebRTC to the dashboard. | P0 | `index.html` vs README; see A6 |
| M6 | **Message for the waiters**: team stats, no punishment metrics, alerts = more tips. | Staff resistance kills adoption. | P0 | absent; tied to Q1 |
| M7 | **Before/after pilot with a "silent mode"** (measure a week without alerts, then with). | Proof sells; stats already exist. | P0 | `ServiceStats.tsx` |
| M8 | **Pricing and packaging** (box sold/rented + monthly per location, camera tiers). | No price anywhere. | P1 | absent |
| M9 | **Time to first alert** as a promise (preconfigured box, remote setup). | RTSP ids are too technical for owners. | P1 | `AddCameraForm.tsx` |
| M10 | **Comparison block** vs call buttons, POS timers, mystery shoppers. | "Why not a call button?" | P1 | absent |
| M11 | **Sales channel**: CCTV installers, POS integrators, HoReCa associations. | A small team can't sell door to door. | P1 | absent |
| M12 | **One beachhead segment**, consistent copy (restaurants vs "4 segments"). | D19 widened the market; copy is mixed. | P0 | `decisions.md` D19, README |
| M13 | **Correlate alerts with Google reviews.** | "Bad days = 2× 1-star reviews" slide. | P2 | absent |
| M14 | **Consistent naming in the UI**: "masă uitată" vs "neservită"; "așteptare" defined from the alert vs from sitting down. | The owner will misread the KPI. | P0 | dashboard copy; I2 |
| M15 | **Name check**: pronunciation, .ro domain, trademark. | | P1 | absent |
| M16 | **Fill in the team section** ("Rol: de completat"). | Looks unfinished. | P0 | `index.html`, README |

## Edge cases

| # | Situation | What should happen | Status | Notes |
|---|-----------|--------------------|--------|-------|
| E1 | A waiter acknowledges, nobody reaches the table. | After X min alert again or escalate to the manager. | open | Q2 |
| E2 | A waiter arrives without acknowledging. | The alert closes; record "no acknowledgement". | open | Check #19 behaviour |
| E3 | A waiter only walks past. | Not an arrival. | done | ≥ 5 s in zone (D23) |
| E4 | Two waiters acknowledge. | First one owns it; alarm stops for everyone. | open | Q5 |
| E5 | Nobody answers an urgent call. | Call the next on the list / call again. | open | Q9 |
| E6 | Many urgent alerts at once. | One summary call, rate limit. | open | |
| E7 | No internet / call provider down. | Fall back to push or a local alarm. | open | Q17 |
| E8 | Edge restarts with alerts open. | Edge re-opens/closes on boot, or the backend auto-expires alerts without heartbeat. | open | A7 |
| E9 | Edge restarts and a queued `confirm_staff` arrives for a reused `track_id`. | Check `suggestion_id`, otherwise a guest becomes staff. | open | `pipeline.py:206` |
| E10 | Zone redrawn or rule edited/disabled while an alert is open. | Close as "config changed", keep it out of wait stats. | open | `engine.py:97-106` |
| E11 | Camera unplugged for 10 min. | "Camera offline" alert; open alerts marked "unknown". | open | A12 |
| E12 | Two cameras see the same table. | De-duplicate at location level or one zone per table. | open | |
| E13 | Backend down 1 h, edge replays its buffer. | Ingest silently, no stale Telegram messages (max age). | open | A7 |
| E14 | Location deleted. | Soft delete; check the cascade doesn't break on the audit trigger. | open | C14 |
| E15 | Same person at two separate orgs (manager at A, staff at B). | Impossible today (email unique globally). Decide: multi-org or companies inside one org. | open | Q13 |
| E16 | Rule copied to a location without that zone tag. | Refuse and list missing zones. | open | C6 |
| E17 | Owner wants to use alerts to discipline staff. | Team-level stats only, stated in the terms. | open | M6, Q1 |
| E18 | Location without IP cameras / cameras managed by a security firm. | Bundled IP camera; the firm becomes a reseller. | open | M11 |
| E19 | Self-service / fast food, staff without uniforms, seasonal terraces. | Lead with queue/uncleared tables; promise less without uniforms; seasonal pause billing. | open | M12 |
| E20 | Pilot shows little improvement. | Report the honest baseline; position as "visibility first". | open | M7 |
| E21 | A guest is cut off by the bottom of the frame (close camera, seated person). | Still counts as at the table. Today "at a table" uses the foot point (bottom-centre of the box); when the box touches the frame edge, the foot point sits on the edge and falls outside a zone that stops short of it, so pose never runs and a raised hand is missed. Proposal: the zone editor snaps zones to the frame edge, and the edge treats a box touching the bottom edge as inside a zone that reaches within a few % of it. | open | Found in the 2026-11-06 cloud camera test: zone to 0.98 → `verified_ratio` 0, zone to 1.0 → raised hand detected. `pipeline.py` `_in_table`. |
| E22 | A guest raises a hand for 2 s, then lowers it; nobody has come yet. | The "clientul cheamă" alert stays open until staff arrive at the table (like "neservită"), instead of closing as "rezolvat" when the hand goes down. | open | Seen in the 2026-11-06 cloud camera test: opened 15:42:36, closed 15:42:38 with no staff. Demo risk: a juror lowers the hand and the alert vanishes. `domain/engine.py` closes when the condition stops holding. |
| E23 | A single frame shows a raised hand (stretching, fixing hair). | No alert. Proposal: the hand must be seen raised for at least ~1 s before the rule fires. | open | Same test: an alert opened and closed within the same second. |
| E24 | A small person in the background (far away, partly hidden) is detected on and off. | No alert opens and closes for them; at most one stable alert. Today each time the track is lost the guest is "absent", so "neservită" opens and closes every 1–10 s and staff would get a notification each time. Proposal: ignore tracks below a minimum box area (e.g. 2–3 % of the frame) for table rules, and/or require an alert to stay open a minimum time (e.g. 15 s) before notifying, with a short grace period (e.g. 5 s) before closing when the guest disappears. **Decided 2026-11-06: do both.** | decided | Seen in the 2026-11-06 cloud camera test: tracks #678 (area 0.12) and #698 (area 0.02) at the frame edges opened and closed z1/z4 alerts four times in 70 s. `domain/engine.py` + rule evaluation in `pipeline.py`. |
| E25 | The phone's USB link re-enumerates (loose contact) and the `adb forward` is lost. | The stream comes back by itself. | open | Live test 2026-11-06: 8 USB disconnects in ~10 min; after each, `adb` was `unauthorized` until the prompt was accepted again ("Permiteți mereu" fixes that). A watcher re-applying `adb forward` every 3 s kept the edge running; candidate for `make edge-usb`. |
| E26 | The camera stream stalls or reconnects while a guest is still seated. | The open alert stays open (state "unknown"), it doesn't close as "rezolvat". | done | **P0 for the demo.** Fixed: a frame more than `max(grace_s, 2 s)` after the previous one shifts every zone timer forward by the gap (timers freeze, grace restarts after it); logged as `stream_gap seconds=…`. Live test 2026-11-06 16:55:49: after a USB drop the first frames had nobody → `Masa 1: rezolvat`. Proposal: on a capture gap > grace, freeze zone timers instead of counting the gap as "absent". Related E11. |
| E27 | The waiter stands behind the seated guest, or too close to the camera with the head cut off. | Still detected as staff. | open | Live test: behind the guest → one box for both; too close and back-lit → not detected. Demo script: the waiter stands in front of the table, whole body in frame, ~2 m from the phone. |
| E28 | Staff arrive before anyone presses "Merg eu". | Counted as an arrival without acknowledgement (works), the alert closes as served. | done | Live test 16:57:34 arrival, 16:57:41 ack — handled; the late ack still returns 200, check whether it should answer "deja servită". |
| E29 | Track ids churn every few seconds at low FPS, so the "standing" ratio and appearance score restart. | Staff stay staff across a lost track. | open | Live test: ids 34→63 in one minute at 5 fps; at 15 fps over USB much better. Proposal: re-identify a new track with the appearance embedding of a just-lost staff track (same profile, < 3 s, nearby box). |
| E30 | Appearance thresholds tuned on one venue's light. | Calibrate per location. | open | Measured 2026-11-06: enrolled staff 0.82–0.91, guests 0.60–0.64 → thresholds 0.70/0.82 (#44). Variant B: learn guest negatives from rejected suggestions ("Nu e angajat") and score staff − guest similarity. |

## Open questions

| # | Question | Who decides | Status | Answer |
|---|----------|-------------|--------|--------|
| Q1 | Who acknowledges: a named waiter or any staff phone? (Per-waiter stats need a name; see M6, E17.) | product | decided | Personal account for each person; statistics shown per team only, never per waiter. |
| Q2 | After an acknowledgement with no arrival, how long until we alert again, and to whom? | product | decided | After 2 min without arrival, alert the whole shift again. |
| Q3 | Must "arrived" be the waiter who acknowledged? | product | decided | Any staff member reaching the table closes the alert. |
| Q4 | Minimum time in zone to count as arrived. | product + edge | done | 5 s (D23) |
| Q5 | Does an acknowledgement stop the alarm on all phones? | product | decided | Acknowledgement stops the alarm on all phones, showing "Ana merge". |
| Q6 | Number of waiters on shift: entered by the manager or counted by the edge? | product | decided | Counted automatically from the camera, manager can correct. (Could also use the "Sunt în tură" count from Q21.) |
| Q7 | Which situations are urgent, or does the owner set severity per rule? | product | decided | Default severity per situation type set by us; the owner can change it per rule. |
| Q8 | Does severity escalate over time (message → call if not acknowledged)? | product | decided | Yes: message first, phone call if nobody acknowledges. |
| Q9 | Who gets called? | product | decided | Location manager; if no answer, the owner. |
| Q10 | Call provider (Twilio-like vs Telegram/WhatsApp), Romanian voice message? | tech | decided | Voice-call provider (Twilio-like) with a Romanian message. |
| Q11 | Quiet hours for calls? | product | decided | Calls only within the location's opening hours. |
| Q12 | **Deployment model**: our multi-tenant cloud, or one backend box per customer? Drives A4–A6, MediaMTX location, the privacy claim. | product + tech | clarified | One shared multi-tenant cloud by default. A dedicated server (own infrastructure) only on a custom Enterprise plan. So A1–A6 must be built multi-tenant. |
| Q13 | **Tenancy shape**: one org with companies/brands inside, or separate orgs + a group owner? | product | decided | One organisation with companies (legal entity, invoice) and brands inside; hidden defaults for single restaurants. |
| Q14 | Staff profile scope: per location, brand or org? | product | decided | Per brand. |
| Q15 | Reference edge hardware, cameras per box, one process per camera or per device? Cost per location per month (Claude, Telegram included)? | tech | decided | One device runs all cameras of a location; measure the limit on the chosen hardware. |
| Q16 | Retention periods (snapshots, events, embeddings, audit); who is controller and who is processor; DPA? | product + legal | decided | Snapshots 7 days, events 12 months, audit 24 months with pseudonymised names; customer = controller, AiVee = processor with a DPA. Verify with a lawyer. |
| Q17 | What does the system promise offline: local alarm or delayed delivery? | product | decided | Edge: local alarm in the room (tablet/speaker) plus delayed delivery. |
| Q18 | Contract versioning across a mixed edge fleet (`schema_version`, compatibility policy)? | tech | decided | Version number in messages; the server accepts the last 2 versions. |
| Q19 | Who installs and adopts a device; self-service pairing in pilot scope? | product | decided | We install during the pilot; CCTV installers afterwards. |
| Q20 | Opening hours: on the location or per rule? Holidays manual or national feed? | product | decided | On the location, with Romanian public holidays prefilled. |
| Q21 | Recipients: model shifts in AiVee or lean on Telegram groups per shift? Owners: pushes or digests? | product | decided | "Sunt în tură" toggle on the phone; owners get a summary, not each alert (escalated calls from Q9 still reach them). |
| Q22 | Selling a location: history to the buyer, kept by the seller, or exported and wiped? | product | decided | History stays with the seller (archived, exportable); the buyer starts clean. |
| Q23 | Rule templates: live-linked or one-time copies? League table visible to managers? | product | decided | Linked templates: an edit propagates to every location (see Q36 for local overrides). League table visible to owners and group roles only. |
| Q24 | Beachhead segment and buyer persona (owner, GM, ops director)? | founders | decided | Pilot with independent table-service restaurants in Sibiu, then small chains (2–10 locations). |
| Q25 | Business model: sell/rent/bundle hardware, monthly price unit (location/camera/device), free pilot? Who installs? | founders | decided | Price per location with a camera limit per plan. Edge offer: both a box included in the Edge add-on (12-month contract) and the edge program on the customer's own PC at a lower add-on. |
| Q26 | Stay MIT open source as a product? What is the moat? | founders | decided | Code stays open (MIT). Not closing it. |
| Q27 | Is the Claude dependency acceptable to privacy-conscious buyers; offline fallback for rule writing? | product + tech | decided | Yes, stated clearly in the terms, plus a manual rule editor as a fallback. |
| Q28 | Languages: Romanian only, or English/Hungarian? | founders | decided | Romanian now, English after the pilot. Only these two languages. |
| Q29 | Pilot success metric agreed with the customer up front? | founders | decided | Median wait and share of tables over the threshold, agreed with the customer before the pilot. |
| Q30 | Keep the name AiVee? | founders | decided | Keep AiVee; check the trademark (OSIM/EUIPO) and the .ro domain now. |
| Q31 | How does the video get from the restaurant to the cloud? Cameras sit behind the router. Options: the camera pushes the stream itself (RTMP/SRT, only some models), a small connector program on any PC/router, or port forwarding (not recommended: security risk). | tech | decided | The camera pushes the stream where it can; otherwise a small connector program on any PC or router. |
| Q32 | Is the upload bandwidth enough? Estimate ~0.3–0.5 Mbps per camera at low resolution; 4 cameras ≈ 2 Mbps upload. To be measured. | tech | decided | Measure in the pilot; require at least 5 Mbps upload for cloud mode, otherwise recommend edge. |
| Q33 | Cloud processing cost per camera per month (GPU workers), and is it below the price of the edge box spread over the contract? | tech + founders | decided | Measure in the pilot and price cloud above cost with a clear margin. |
| Q34 | GDPR in cloud mode: guest video is processed by us. Is it stored at all (proposal: never, processed in memory only)? Server location (EU)? Encryption in transit? Needs a DPIA. | product + legal | decided | Store no video: process in memory and discard; EU servers; encrypted transport; DPIA checked by a lawyer. |
| Q35 | What happens in cloud mode when the internet drops: no alerts at all. Acceptable for the cheapest plan, with the edge sold as the fix? | product | decided | No alerts; the app clearly shows "locație offline"; edge is sold as the fix. |
| Q36 | Linked rule templates (Q23): can a location override one field? E.g. the brand rule says 5 min, the terrace location wants 7 min. Proposal: local overrides per field; template edits propagate to every field not overridden. | product | decided | Yes: a location may override single fields; template edits propagate to every field it has not overridden. |
| Q37 | **Licence of dependencies.** The edge uses Ultralytics YOLO11 (`apps/edge/pyproject.toml:10`), licensed AGPL-3.0 (to verify). Closed code (Q26) and especially cloud mode (I4) would need an Ultralytics commercial licence or a switch to a permissively licensed detector. | founders + tech | decided | Code stays open, so no commercial licence needed for that reason. Still verify the Ultralytics licence and comply with AGPL-3.0 if confirmed: the source of what runs in our cloud must be available to its users. |
| Q38 | Closing the code (Q26): versions already published under MIT stay MIT forever. Changing the licence needs the agreement of all three authors in `LICENSE`. Do the hackathon rules require public or open-source code? The site and README link to GitHub. | founders | decided | Moot: the code stays open. |
| Q39 | Should the per-shift headcount (Q6) come from the "Sunt în tură" toggle (Q21) first, with the camera count as a cross-check? | product | decided | Yes: headcount from the "Sunt în tură" toggle first, camera count as a cross-check. |
