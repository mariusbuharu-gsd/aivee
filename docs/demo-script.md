# Demo script — 4 minutes

Judging Saturday 7 November, 11:30–15:00. Code freeze 10:30. Everything below uses what is on `develop`:
screen names, button labels and alert texts are copied from the code.

## Roles

| Who | Plays | Holds |
|---|---|---|
| **Presenter** | drives the dashboard and narrates | presenter laptop (owner, `owner@aivee.demo`), projector |
| **Radu** | the guest | **his laptop on the table** (the camera, **Laptop Radu**); sits at **Masa 1** |
| **Marius** | the staff member, in the **purple hoodie** | phone logged in as `staff@aivee.demo`, Alerte open |

Nobody presses anything to "take" an alert: there is no "Preiau" any more. The camera sees staff arrive
and closes the alert on its own.

## Set-up the demo assumes

- **The server plays the cloud.** The standard offer is cloud-first (D25): cameras stream to our EU cloud,
  video is analysed and discarded. In the demo the GSD server (`https://app-aivee.earth.sv.gsd.com.ro`) is
  that cloud, and Radu's laptop is just a camera on the table. Say this once, in step 1.
- Camera **Laptop Radu** (`cam-coleg-2`): Radu's laptop on the table, webcam facing the guest's seat and the
  way staff come in. Zones **Masa 1** (tag `table`) and **Intrare** (tag `entrance`) drawn on today's view.
  **Laptop coleg 1** (`cam-coleg-1`) is not used: all its rules are off.
- Two rules already created and confirmed on Reguli for Laptop Radu (not live):
  - „Client neservit (demo 10 s)” on Masa 1 (present guest 10 s ∧ absent staff 10 s) → Telegram;
  - „Foc în imagine” (cooldown 30 s).
- The raised-hand rule is **not** created yet: it is the one written live in step 2.
- Marius, in the purple hoodie, is enrolled as staff through `/angajat-nou`, so Live labels him „angajat”.
- Ingest runs with `REMIND_S=60`: while nobody has arrived, a ⏰ reminder every 60 s.

## Timeline (total 4:00)

| # | Time | Step | Budget |
|---|---|---|---|
| 1 | 0:00 | Login → location → live camera with boxes | 0:20 |
| 2 | 0:20 | Write a rule in Romanian → "Ce am înțeles" → confirm | 0:35 |
| 3 | 0:55 | Radu sits at Masa 1 → alert after 10 s → ⏰ reminder at +60 s | 1:10 |
| 4 | 2:05 | Marius walks over → "✅ Rezolvat" (or Radu leaves → "👋 clientul a plecat") | 0:25 |
| 5 | 2:30 | Guest raises a hand → alert | 0:20 |
| 6 | 2:50 | Istoric shows everything | 0:25 |
| 7 | 3:15 | Metrici: wait times | 0:25 |
| — | 3:40 | Close: one sentence + team | 0:20 |

### 1. Login → location → live (0:00–0:20)

- **Presenter:** open `https://app-aivee.earth.sv.gsd.com.ro/intra` → Email `owner@aivee.demo`, Parolă → **Intră în cont**.
- **Presenter:** the sidebar shows the location → **Live** → **Laptop Radu**.
- **Expected:** the camera tile with the live video and the zone outlines; Marius, standing away from the table,
  labelled „angajat”.
- **Say:** "A normal camera, nothing to buy: here, a laptop on the table. The video goes to our cloud, is
  analysed and discarded. The same software can run on the customer's own PC: that is the edge option.
  AiVee sees roles, not faces."
- **Fallback:** no image ("fără imagine" on Camere) → Radu restarts the camera script. Server or Wi-Fi down →
  the backup laptop stack (`make up`, api, dashboard, `make edge-usb` with the phone on USB), same scenario;
  no camera at all → `make fake-edge SCENARIO=unattended SPEED=2` on the backup stack and say "this is the same
  pipeline fed by a scripted scene".
- **Fallback without a live camera at all:** Analiză video (`/video`) on the backup stack → upload
  `recordings/sala-1.mp4`, copy zones and rules from a live camera → the timeline lists each alert at its mm:ss
  with the blurred snapshot. Say: "the same pipeline and the same rules, on a recording; it does not ring the
  staff's phones".

### 2. A rule in Romanian (0:20–0:55)

- **Presenter:** **Reguli** → type (or dictate with the microphone button):
  "Dacă cineva ridică mâna la masă, cheamă ospătarul" → **Creează regula**.
- **Expected:** after a few seconds ("Se analizează…") the box **Ce am înțeles** with the rule name, the
  pill "ciornă" and the plain-Romanian description; "Vezi regula JSON" shows the typed rule.
  (Eval: this exact request → `pose guest raised_hand`, 3.6 s; all 20 eval requests median 2.4 s.)
- **Presenter:** **Confirmă și salvează**. The rule appears in the list and is pushed to the camera's worker.
- **Say:** "The model only proposes; the owner confirms. Ask it to recognise a person and it refuses."
- **Fallback:** no internet / Claude error (Romanian error message) → say "creating rules needs the internet;
  rules that already exist keep running", and show the two pre-created rules. Step 5 then has no hand rule:
  skip it.

### 3. The guest waits → alert → reminder (0:55–2:05)

- **Radu:** sit at Masa 1. **Marius:** stay away from the table.
- **Expected after ~10 s:** in the dashboard a coral alert **"Masa 1 așteaptă de 10 s"**; in the Telegram group
  **AiveeAlerts** the same alert with the blurred snapshot and one button, **Vezi în aplicație**; on Marius's
  phone a push notification.
- **Say:** "Nobody came for ten seconds, so AiVee raises it. In a real restaurant this would be a minute or two."
- **While the minute runs:** show the alert card on Live and the Telegram message; explain that the camera, not
  a button, will close it.
- **Expected 60 s after the alert:** a reply to that Telegram alert **"⏰ Încă neservit: Masa 1, de 1 min"**,
  and again every 60 s while nobody comes.
- **Say:** "If nobody reacts, it keeps reminding, without anyone pressing anything."
- **Fallback:** no alert 30 s after Radu sat down → check Dispozitive (camera online?) and that Marius is not inside Masa 1.
  Telegram silent but dashboard OK → carry on; Telegram is a notifier, not the pipeline. Push silent → carry on
  with Telegram (push needs HTTPS and permission on the phone).

### 4. Staff arrives → "✅ Rezolvat" (2:05–2:30)

- **Marius:** walk to Masa 1 and **stay at least 5 s** (`ARRIVE_S`); serve Radu.
- **Expected:** on Live Marius is „angajat”; in Telegram a follow-up **"Un angajat a ajuns la Masa 1 după …"**,
  and the original alert is edited: it now starts with **"✅ Rezolvat · un angajat a ajuns după …"** and has no
  buttons. The reminders stop. In Alerte, the timeline **Deschisă** → **Ajuns** ("după …") → **Închisă**.
- **Say:** "Arrival is what the camera saw, not a button a busy waiter forgets. The alert closes itself, and the
  wait is measured, per alert."
- **If Radu leaves instead** (nobody came in time, or as a second run): Radu gets up and leaves the frame.
  **Expected ~10 s later:** **"👋 Clientul a plecat de la Masa 1 fără să fie servit (a așteptat …)"**, and the
  original alert becomes **"⚪ Închisă · clientul a plecat"**. **Say:** "And when a guest gives up, the owner
  knows that too."
- **Fallback:** no "a ajuns" → Marius is probably labelled guest: stand still, fully in the zone, 5 s more.

### 5. The guest raises a hand (2:30–2:50)

- **Marius:** step out of Masa 1. **Radu:** raise a hand clearly above the shoulder, 2–3 s.
- **Expected:** alert **"Masa 1: un client cheamă"** within a few seconds, Telegram + push.
- **Say:** "That is the rule we wrote two minutes ago, already running."
- **Fallback:** pose only runs inside table zones: Radu must be fully in Masa 1. Still nothing → move on.

### 6. Istoric (2:50–3:15)

- **Presenter:** **Istoric**.
- **Expected, newest first:** the hand rule created by the owner (with before/after), the alerts opened by the
  camera, arrived, closed, the login. Filter by kind **Alerte** to narrow it.
- **Say:** "Append-only, enforced in Postgres: not even the app can rewrite it. Staff see only their own actions."

### 7. Metrici (3:15–3:40)

- **Presenter:** **Metrici**.
- **Expected:** **Așteptare** (median and p90), from the arrival times, including the alert from step 4, and the
  alert count; below, FPS, CPU and verified frames per device.
- **Say:** "This is the owner's question: how long do guests wait before someone gets to them."

### Close (3:40–4:00)

"AiVee: the staff's extra pair of eyes, configured in Romanian, private by design, with the cameras you already
have. In our EU cloud as standard, or on your own PC if the video must never leave. Marius, Radu — thank you."

## Pre-demo checklist (T−30 min)

- [ ] Camera phone on USB to the laptop, USB debugging allowed ("Allow USB debugging" accepted), IP Webcam
      started (**Start server**) with FPS limit 15 and quality 50. USB, because the venue Wi-Fi stalls the stream.
- [ ] Camera phone charging, screen kept on (no sleep, no lock).
- [ ] Marius's phone charged, logged in as `staff@aivee.demo`, Alerte open, **Notificări pe telefon** = active,
      **Trimite un test** received. Do not disturb off, volume up.
- [ ] `make up` healthy; `make seed` run; `make edge-usb` running (adb forward to port 28080, ROTATE=90,
      APPEARANCE=true, TARGET_FPS=30); Dispozitive shows `edge-01` online.
- [ ] Marius enrolled as staff in the purple hoodie through `/angajat-nou` (20 s capture); Live labels him
      „angajat”. No other staff profiles.
- [ ] Arrival rehearsed: Marius walks to Masa 1 and stands still 3–4 s by the table, so "a ajuns" fires
      (`ARRIVE_S` = 5 s counts from entering the zone).
- [ ] Zones clean: Masa 1, Intrare drawn on Laptop Radu on today's camera position (the camera did not move).
      Nobody sitting at a table zone before the demo (no stale alerts); Alerte has no open alert.
- [ ] Server ingest has `REMIND_S=60`; a rehearsal alert got its ⏰ reply 60 s after it opened.
- [ ] Rules created (`make seed` creates accounts only, not rules): „Client neservit (demo 10 s)” and
      „Foc în imagine” on Laptop Radu, confirmed and shown as "activă" on Reguli; the hand rule **not**
      created yet.
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
      dashboard URL on Marius's phone.
- [ ] Marius in the purple hoodie; Radu's laptop on the table runs the camera script.
- [ ] Laptop on power, screen sleep off, browser zoom so the alert card is readable from the back.

## Elevator pitch (60 s, Romanian)

> Oamenii află prea târziu ce se întâmplă în fața camerelor lor, pentru că nimeni nu are timp să se uite la ele.
> Într-un restaurant asta înseamnă un client care așteaptă la masă și nu e văzut.
>
> AiVee e perechea de ochi în plus a personalului. Nu cumperi nimic: conectezi camerele pe care le ai deja,
> iar imaginea e analizată în cloud-ul nostru, cu servere în UE, și aruncată, nu e salvată niciodată. În demo,
> laptopul ține locul serverului din cloud. Desenezi mesele, scrii o regulă în română — „Anunță ospătarul dacă
> la o masă nu a venit nimeni de un minut" — și AiVee o transformă într-o regulă pe care tu o confirmi. Când
> clientul așteaptă, ospătarul primește alerta pe telefon și AiVee îi reamintește până vine cineva; camera vede
> când a ajuns la masă și închide alerta singură. Proprietarul vede cât au așteptat clienții, care au plecat
> neserviți și tot istoricul, care nu poate fi modificat.
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
