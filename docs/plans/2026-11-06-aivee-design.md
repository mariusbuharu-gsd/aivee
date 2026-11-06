# AiVee — Design (Astra Hack, 6–7 Nov 2026)

## Problem

People learn too late what happens in front of their cameras, because nobody has time to watch them.

## Product

AiVee is the staff's extra pair of eyes for restaurants, terraces and events.
The owner points an existing camera at the room, draws zones (tables, entrance),
describes the staff in Romanian ("waiters wear a burgundy T-shirt") and optionally
uploads 2–3 photos. AiVee then alerts staff on their phone when a guest waits too long.

### MVP events (each one is a rule written in Romanian)

| # | Event | Situation |
|---|---|---|
| 1 | Unattended table | `present(guest, table, ≥1m) ∧ absent(staff, table, ≥X)` |
| 2 | Guest calls | `pose(raised_hand, table)` |
| 3 | Queue at entrance | `count(guest, entrance) ≥ N ∨ present(guest, entrance, ≥3m)` `∧ absent(staff, entrance)` |
| 4 | Table not cleared | `objects(cup/plate/bottle, table) ∧ absent(person, table, ≥5m)` |

### Innovation

1. **Configured in Romanian**: Claude turns a request into a validated rule (JSON).
2. **Roles learned from examples and behaviour, no training**:
   - *appearance*: CLIP/SigLIP embedding of each person crop vs. staff examples;
   - *behaviour*: distance per minute, tables visited, % stationary, staff zones;
   - fused into `staff_score`; the owner confirms suggested staff with one tap and the
     confirmed crops become new examples (self-labelling loop).
3. **Situations over time, not objects**: presence, absence, count, pose, duration.

### Privacy

No face recognition: AiVee identifies the **role**, not the person. Faces are blurred on
the device; video never leaves it; only alerts and blurred snapshots are sent.
Face recognition is out of scope (GDPR art. 9 biometrics, EU AI Act, model licences).

### Positioning vs. existing tools

Surveillance products (e.g. Agent DVR) already offer object detection and LLM hooks.
AiVee differs through situations over time, learned roles and rules in Romanian.
It plugs into existing cameras/DVRs via RTSP.

## Architecture

```
CAMERA ─RTSP─► EDGE (Python, CPU + OpenVINO)
               detect people + objects (YOLO) ─ every frame
               track (ByteTrack) ─► trajectories
               role per track: appearance embedding (~every 2 s) + behaviour ─► staff_score
               pose (YOLO Pose) only inside table zones
               situation engine: present / absent / count / pose / objects + duration
               optional verification (Moondream) only on alerts
               face blur ─► snapshot
                 │ MQTT (Mosquitto: ACL, LWT, retained, QoS 1, shared subscriptions)
  events · status · metrics · snapshots · suggestions ▲ rules · profiles (retained)
                 │
MOSQUITTO ◄──► INGEST ──► POSTGRES + pgvector
                 │
               API (FastAPI) ── Claude: request → rule; enrolment: photos/video → profiles
                 ▼
        Web dashboard + PWA (zones, rules, confirm staff, push alerts)
        Live video: EDGE ─► MediaMTX ─► WebRTC
```

Repository: uv workspace; `packages/contracts` (Pydantic, single source of truth, generates
JSON Schema and TS types); `apps/{edge,api,ingest,dashboard,site}`; pure `domain/` code behind
`Protocol` ports with adapters for YOLO, CLIP, MQTT, Postgres, Telegram and Claude.

## Scope (MoSCoW)

- **Must**: phone stream → person detection + tracking; zones; behaviour role; situation
  engine; events 1 and 2; Romanian request → rule; MQTT → ingest → Postgres → Telegram;
  dashboard (live, zones, alerts).
- **Should**: appearance role + "looks like staff → confirm" loop; events 3 and 4; face blur;
  metrics page; PWA with push; presentation site.
- **Could**: Moondream verification; enrolment from video; YOLOE visual prompts.
- **Won't**: face recognition; wildlife/fire scenarios; cloud processing; native apps; multi-tenant auth.

## Demo (~4 min)

1. Draw table 1, table 2, entrance; type "Anunță ospătarul dacă la o masă nu a venit nimeni
   de 1 minut" → the rule appears.
2. A teammate walks between tables → "looks like staff, confirm?" → confirm; upload a T-shirt photo.
3. Two teammates sit; nobody comes → alert after 1 min (Telegram + PWA); waiter arrives → alert closes.
4. Someone raises a hand → instant alert.
5. A jury member dictates a new rule; it runs live.

Fallback: every scene recorded; `tools/fake_edge.py` replays recordings.

## Testing

| Level | Examples |
|---|---|
| Unit (most) | `absent(staff, table, 10m)` on simulated timelines; cooldown and alert close; behaviour score on synthetic trajectories; point-in-polygon; role score fusion |
| Contract | Pydantic ↔ JSON Schema ↔ TS types; MQTT payload examples valid |
| Integration | testcontainers: MQTT event → Postgres row, duplicate ignored; LWT → offline; retained rule on reconnect; pgvector nearest profile |
| Evals | 20 Romanian requests → correct rule (score X/20); role classification precision/recall on recorded clips; frame-to-alert latency |

## Milestones

- **M1 14:30**: a person in a table zone for 1 min → Telegram alert via MQTT and Postgres.
- **M2 18:30**: rule from Romanian request; behaviour role; raised hand.
- **M3 00:00 (feature freeze)**: appearance role + confirm; queue; table not cleared; metrics.
- **Sat 10:30 code freeze**: slides, site and backup video ready.
