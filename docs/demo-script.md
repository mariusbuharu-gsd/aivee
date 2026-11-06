# Demo script — 4 minutes, 3 people

Judging Saturday 7 November, 11:30–15:00. Code freeze 10:30. Everything below uses what is on `develop`:
screen names, button labels and alert texts are copied from the code.

## Roles

| Who | Plays | Holds |
|---|---|---|
| **Marius** | narrator, drives the dashboard | laptop (owner, `owner@aivee.demo`), projector |
| **Radu** | the guest | 2–3 cups, sits at **Masa 1** |
| **Vasi** | the staff member, wearing the black jacket | phone logged in as `staff@aivee.demo` (Ana Ospătar), Alerte page open |

## Set-up the demo assumes

- **The laptop plays both roles.** The standard offer is cloud-first (D25): cameras stream to our EU cloud,
  video is analysed and discarded. In the demo, the laptop stands in for that cloud server, and the fact
  that it runs on a plain laptop CPU is the edge option. Say this once, in step 1; don't claim a real cloud.
- Location `demo` ("Terasa demo"), camera `cam-01` on device `edge-01` (D15), zones **Masa 1**, **Masa 2**
  (tag `table`) and **Intrare** (tag `entrance`) drawn on the camera still.
- Two rules already created and confirmed on Reguli (created the evening before, not live):
  - "Anunță ospătarul dacă la o masă nu a venit nimeni de 1 minut" (eval case 1 → present guest 60 s ∧ absent staff 60 s);
  - "Anunță dacă o masă rămâne nedebarasată un minut după ce au plecat clienții" — check that "Ce am înțeles"
    shows 1 minute before confirming (the eval's default for this kind of request is 5 min).
- The raised-hand rule is **not** created yet: it is the one written live in step 2.
- Vasi, in the black jacket, is enrolled as the staff profile (photos on the profile) and/or has been confirmed once
  through "Pare angajat — confirmi?", so the edge already tags him as staff (light blue box).

## Timeline (total 4:00)

| # | Time | Step | Budget |
|---|---|---|---|
| 1 | 0:00 | Login → location → live camera with boxes | 0:20 |
| 2 | 0:20 | Write a rule in Romanian → "Ce am înțeles" → confirm | 0:35 |
| 3 | 0:55 | Guest has been sitting since 0:15 → alert at ~1:15 on Telegram + push | 0:25 |
| 4 | 1:20 | "Merg eu" on the phone → walk → arrived → closed, with times | 0:40 |
| 5 | 2:00 | Guest raises a hand → alert | 0:20 |
| 6 | 2:20 | Both leave Masa 1, cups stay → wait 1 min | (runs in background) |
| 7 | 2:20 | Istoric shows everything | 0:30 |
| 8 | 2:50 | Metrici: wait / reaction / travel | 0:30 |
| 6b | 3:20 | "Masa 1: nedebarasată de 1 min" arrives | 0:20 |
| — | 3:40 | Close: one sentence + team | 0:20 |

The two 1-minute waits overlap with talking: Radu sits down during step 1, and the cups are left before
Istoric and Metrici.

### 1. Login → location → live (0:00–0:20)

- **Marius:** open `http://localhost:5173/intra` → Email `owner@aivee.demo`, Parolă → **Intră în cont**.
- **Marius:** in the sidebar, the location shows **Terasa demo** (a dropdown when the owner has more than one
  location) → **Live**.
- **Radu:** at 0:15, walk into the frame and sit at Masa 1.
- **Expected:** the camera tile with the live video, the zone outlines, a white box on Radu (guest) and a light
  blue box on Vasi (staff) standing near the bar.
- **Say:** "A normal camera, nothing to buy. In the demo this laptop stands in for our cloud server. And because
  it is just a laptop CPU, the same software can run on the customer's own PC: that is the edge option. AiVee
  sees roles, not faces."
- **Fallback:** no video or no boxes → in a second terminal `make edge SOURCE=recordings/sala-1.mp4`
  (the recorded clip, already upright). Still nothing → `make fake-edge SCENARIO=unattended SPEED=2`
  and say "this is the same pipeline fed by a scripted scene". Login fails → `make seed` was not run or
  `DEMO_PASSWORD` changed; run `make seed` (it resets the three demo users).
- **Fallback without a live camera at all:** Analiză video (`/video`) → upload `recordings/sala-1.mp4`, copy
  zones and rules from cam-01 → the timeline lists each alert at its mm:ss with the blurred snapshot. Say:
  "the same pipeline and the same rules, on a recording, as fast as the laptop can go; it does not ring the
  staff's phones".

### 2. A rule in Romanian (0:20–0:55)

- **Marius:** **Reguli** → type (or dictate with the microphone button):
  "Dacă cineva ridică mâna la masă, cheamă ospătarul" → **Creează regula**.
- **Expected:** after a few seconds ("Se analizează…") the box **Ce am înțeles** with the rule name, the
  pill "ciornă" and the plain-Romanian description; "Vezi regula JSON" shows the typed rule.
  (Eval: this exact request → `pose guest raised_hand`, 3.6 s; all 20 eval requests median 2.4 s.)
- **Marius:** **Confirmă și salvează**. The rule appears in the list and is pushed to the edge (retained MQTT).
- **Say:** "The model only proposes; the owner confirms. Ask it to recognise a person and it refuses."
- **Fallback:** no internet / Claude error (Romanian error message) → say "creating rules needs the internet;
  rules that already exist keep running here", and show the two pre-created rules. Step 5 then has no hand rule: use
  `uv run python tools/fake_edge.py --scenario hand --speed 2 --demo` (built-in demo rules, ignores the
  retained ones).

### 3. The guest waits → alert (0:55–1:20)

- **Marius:** go back to **Live** (or **Alerte**). Talk about the minute while it runs: "Radu sat down at 0:15.
  Nobody from staff has come. At one minute AiVee raises it."
- **Expected at ~1:15:** in the dashboard a coral alert **"Masa 1: neservită de 1 min"** with a **Merg eu**
  button; in the Telegram group a message with the blurred snapshot; on Vasi's phone a push notification.
- **Vasi:** show the phone notification to the jury.
- **Fallback:** no alert after 1:30 → check Dispozitive (device online?) and that Vasi is not inside Masa 1.
  Still nothing → `make fake-edge SCENARIO=unattended SPEED=2` (opens after ~30 s, staff arrives at ~48 s).
  Telegram silent but dashboard OK → carry on; Telegram is a notifier, not the pipeline. Push silent →
  carry on with Telegram (push needs HTTPS on the phone).

### 4. "Merg eu" → arrived → closed (1:20–2:00)

- **Vasi:** tap the notification (opens **Alerte**) → **Merg eu**.
- **Expected:** the timeline under the alert: **Deschisă** → **Preluată** (Ana Ospătar, "reacție …").
- **Vasi:** walk to Masa 1 and **stay at least 5 s** (`ARRIVE_S`); serve Radu.
- **Expected:** **Ajuns** ("drum …"), a second Telegram message "Ana Ospătar a ajuns la Masa 1 după …", then
  **Închisă** with "așteptare …".
- **Say:** "Arrival is what the camera saw, not a button a busy waiter forgets. Wait, reaction and travel are
  measured, per alert."
- **Fallback:** no "Ajuns" → Vasi is probably tagged as guest: stand still, fully in the zone, 5 s more. If the
  alert closes without arrival, show the "fără preluare" / closed state and move on. "Merg eu" returns an error
  → someone already took it (409); refresh.

### 5. The guest raises a hand (2:00–2:20)

- **Vasi:** step out of Masa 1. **Radu:** raise a hand clearly above the shoulder, 2–3 s.
- **Expected:** alert **"Masa 1: un client cheamă"** within a few seconds, Telegram + push.
- **Say:** "That is the rule we wrote two minutes ago, already running."
- **Fallback:** `make fake-edge SCENARIO=hand SPEED=2` (the scripted guest is at Masa 2). Pose only runs inside
  table zones: Radu must be fully in Masa 1.

### 6. Cups left → "masă nedebarasată" (2:20, result at ~3:20)

- **Radu and Vasi:** leave Masa 1 and the frame; the cups stay on the table.
- **Expected after ~1 min:** **"Masa 1: nedebarasată de 1 min"** in Alerte and on Telegram.
- **Fallback:** cups not detected (small objects, top-down angle) → `make fake-edge SCENARIO=uncleared SPEED=4`
  (opens after 60 simulated seconds, ~15 s at speed 4).

### 7. Istoric (2:20–2:50)

- **Marius:** **Istoric**.
- **Expected, newest first:** the hand rule created by Olga Proprietar (with before/after), the alert opened by
  `edge-01`, acknowledged by Ana Ospătar, arrived, closed, the login. Filter by kind **Alerte** to narrow it.
- **Say:** "Append-only, enforced in Postgres: not even the app can rewrite it. Staff see only their own actions."

### 8. Metrici (2:50–3:20)

- **Marius:** **Metrici**.
- **Expected:** **Așteptare**, **Reacție**, **Drum** (median and p90) including the alert from step 4; below,
  FPS, CPU and verified frames per device.
- **Say:** "This is the owner's question: how long do guests wait, and how fast do we react."
- Then back to **Alerte** for 6b.

### Close (3:40–4:00)

"AiVee: the staff's extra pair of eyes, configured in Romanian, private by design, with the cameras you already
have. In our EU cloud as standard, or on your own PC if the video must never leave. Marius, Radu, Vasi — thank you."

## Pre-demo checklist (T−30 min)

- [ ] Camera phone on USB to the laptop, USB debugging allowed ("Allow USB debugging" accepted), IP Webcam
      started (**Start server**) with FPS limit 15 and quality 50. USB, because the venue Wi-Fi stalls the stream.
- [ ] Camera phone charging, screen kept on (no sleep, no lock).
- [ ] Vasi's phone charged, logged in as `staff@aivee.demo`, Alerte open, **Notificări pe telefon** = active,
      **Trimite un test** received. Do not disturb off, volume up.
- [ ] `make up` healthy; `make seed` run; `make edge-usb` running (adb forward to port 28080, ROTATE=90,
      APPEARANCE=true, TARGET_FPS=30); Dispozitive shows `edge-01` online.
- [ ] Staff profile enrolled with 8–10 photos of Vasi in the black jacket (front, side, back), uploaded on the
      Alerte page or with `POST /api/staff/photos`; Live shows Vasi with the light blue (staff) box.
- [ ] Arrival rehearsed: Vasi walks to Masa 1 and stands still 3–4 s by the table, so "a ajuns" fires
      (`ARRIVE_S` = 5 s counts from entering the zone).
- [ ] Zones clean: Masa 1, Masa 2, Intrare drawn on today's camera position (the camera did not move).
      Nobody sitting at a table zone before the demo (no stale alerts); Alerte has no open alert.
- [ ] Rules created (`make seed` creates accounts only, not rules): unattended 1 min and uncleared 1 min
      confirmed and shown as "activă" on Reguli; the hand rule **not** created yet.
- [ ] Telegram group "AiveeAlerts" open on a visible screen; `TELEGRAM_PREFIX` empty.
- [ ] Notifications allowed in the laptop browser too.
- [ ] Backup clips present and playing: `ls recordings/` — one clip per scene, made with
      `make record SOURCE=http://<phone>:8080/video SECONDS=60 ROTATE=90 NAME=<scene>`.
- [ ] Fake edge tested once: `make fake-edge SCENARIO=unattended SPEED=10`.
- [ ] Analiză video ready: `MQTT_UPLOAD_USER` / `MQTT_UPLOAD_PASSWORD` in `.env` (`make keys`), mosquitto
      restarted once since, `make data-dirs`, migrations at head. Upload `recordings/sala-1.mp4` on `/video`
      with "Copiază zonele și regulile de la" = cam-01 once before the demo, so a finished timeline is there
      to show even if there is no time to wait for a new run. It never rings the staff's phones.
- [ ] Wi-Fi fallback (USB fails): laptop hotspot configured; phone and camera phone know it;
      `ROTATE=90 APPEARANCE=true TARGET_FPS=30 make edge SOURCE=http://<phone>:8080/video`, and update the
      dashboard URL on Vasi's phone.
- [ ] Vasi in the black jacket; Radu has the cups.
- [ ] Laptop on power, screen sleep off, browser zoom so the alert card is readable from the back.

## Elevator pitch (60 s, Romanian)

> Oamenii află prea târziu ce se întâmplă în fața camerelor lor, pentru că nimeni nu are timp să se uite la ele.
> Într-un restaurant asta înseamnă un client care așteaptă la masă și nu e văzut.
>
> AiVee e perechea de ochi în plus a personalului. Nu cumperi nimic: conectezi camerele pe care le ai deja,
> iar imaginea e analizată în cloud-ul nostru, cu servere în UE, și aruncată, nu e salvată niciodată. În demo,
> laptopul ține locul serverului din cloud. Desenezi mesele, scrii o regulă în română — „Anunță ospătarul dacă
> la o masă nu a venit nimeni de un minut" — și AiVee o transformă într-o regulă pe care tu o confirmi. Când
> clientul așteaptă, ospătarul primește alerta pe telefon, apasă „Merg eu", iar camera vede când a ajuns la
> masă. Proprietarul vede cât au așteptat clienții, cât de repede a reacționat echipa și tot istoricul, care
> nu poate fi modificat.
>
> AiVee recunoaște rolul, nu persoana: angajat sau client, după uniformă și comportament. Fețele sunt
> blurate în orice poză. Și pentru că totul merge pe procesorul unui laptop obișnuit, cine vrea ca video-ul
> să nu plece din locație alege varianta edge, pe calculatorul lui.

## Likely jury questions

**1. Privacy and GDPR — you film guests.**
AiVee does no face recognition and stores no identity: it decides only "guest" or "staff", from uniform and
movement (ADR 5). Faces are blurred in every snapshot, in both modes. In the cloud (standard), video is analysed
in memory and discarded, never stored, on EU servers; in edge mode, video never leaves the location. The rule
request sends text only. Requests like "recognise Ion" are refused by design (eval case 17). The camera is the
venue's existing one, under the venue's existing notice; AiVee adds no biometric processing. Cloud processing
of guest video still needs a DPIA and a lawyer's review before launch; we say so.

**2. Why cloud first, and why also edge?**
Cloud removes the hardware barrier: a restaurant starts with the cameras it has, nothing to install on site but
the cameras (or a small connector). Edge is for venues that want video to never leave, or that need to keep
working offline. The pipeline is cheap enough for both: on a laptop CPU (i7-1355U, no GPU) we measured about
20 FPS detection and 12 FPS with pose, per stream; the phone camera, at 8–11 FPS, is the limit, not the model.
Decision D25, `docs/adr/0011-cloud-or-edge-analysis.md`. Today's demo runs everything on this laptop.

**3. What does it cost per location?**
In the cloud, no hardware for the customer. Our cost per camera stream is not measured yet: we will measure it
in the pilot and price above it, so we give no figure. Edge runs on a PC the customer already has, or on our box;
no GPU needed (numbers above). The only paid API call is turning a request into a rule, and rules are created
rarely (ADR 6).

**4. How does it scale to 100 locations?**
In the cloud, analysis scales by stream: the plan is one vision worker per camera stream, reusing the same
domain code (roadmap P5.2, not built yet). In edge mode a new location adds a PC or a box, not load on a central
server. Either way, only alerts, metrics and small blurred JPEGs travel over MQTT. Ingest workers share the event stream
(`$share`), inserts are idempotent, each edge gets its complete rules and config as retained messages on
connect, and each device has its own MQTT user and ACL. Accounts are already organization → location →
devices with roles per location. Today's limits: one broker, one Postgres and one API per deployment
(architecture §9).

**5. Accuracy and false alarms?**
Rule translation is measured: 20/20 on our Romanian eval, median 2.4 s. Vision precision on recorded clips is
not measured yet, so we do not quote a number. False alarms are kept down by design: conditions need a
duration (one minute, not one frame), a 5 s grace for detector flicker (an alert closes about 5 s after the guest really leaves), role hysteresis (staff above 0.7, guest
below 0.4), arrival only after 5 s in the zone, a cooldown per rule, and the owner confirms staff suggestions.
Rules stay drafts until a human confirms them.

**6. Ultralytics YOLO is AGPL. Can you run it in a cloud?**
Yes, if we comply. Our own code is MIT; the detector, Ultralytics YOLO, is AGPL-3.0 (D26). AGPL also covers
network use, so when it runs in our cloud, or ships on an edge box or a customer's PC, the full source of what
runs, including our changes, must be available to its users. Our code is already public, so that is how we
comply; the alternative is an Ultralytics Enterprise licence.

**7. What if the internet goes down?**
In cloud mode, honestly: no alerts until it is back, and the app should show the location as offline (planned,
roadmap P5.5). That is why edge exists: with the analysis on site, detection and rules keep running locally.
But today alerts reach phones through Telegram and Web Push, which need the internet. A local alarm in the room
(a tablet that sounds and lists open alerts when the internet is down) is on the roadmap (P3.6), not built today.
