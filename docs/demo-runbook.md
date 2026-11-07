# Demo runbook — Astra Hack, Sat 2026-11-07

The presenter script is `docs/demo-script.md`. This file is the operational side: what runs
where, the rehearsal checklist, fallbacks, and what not to show.

## What runs where

| Piece | Where | Who starts it |
|---|---|---|
| Dashboard, api, ingest, vision workers | GSD swarm, `https://app-aivee.earth.sv.gsd.com.ro` (stack `aivee-demo`) | always on |
| Demo camera **Laptop Radu** (`cam-coleg-2`) | **Radu's laptop on the table**, webcam on Masa 1 → connector script → server | Radu, in **his own terminal** (not an agent session) |
| **Laptop coleg 1** (`cam-coleg-1`) | not used in the demo | all its rules **off** |
| Phone camera **Telefon 1** (`cam-telefon-1`) | any phone → `/telefon?camera=cam-telefon-1`, held **landscape** | the phone holder |
| Telegram | bot `@aivee_sibiu_bot`, group **AiveeAlerts**, polled by the **server** ingest | always on |
| Backup | laptop stack (`make up`, api, dashboard, `make edge-usb`) with the phone on USB | presenter, only if the server or Wi-Fi fails |

Accounts: `owner@aivee.demo`, `manager@aivee.demo`, `staff@aivee.demo` (password `DEMO_PASSWORD` in
`~/aivee-demo/aivee.env` on the manager; never in chat or docs).

The laptop stack shares the bot, so its `.env` has `TELEGRAM_POLL=false`: only one poller per bot.

## Before 10:30 (setup, ~15 min)

1. Put Radu's laptop on the table, webcam facing the guest's seat and the way staff come in; start the
   camera script; check **Live → Laptop Radu** shows the room.
2. **Camere → Laptop Radu → Editează zonele**: draw **Masa 1** (table) and **Intrare** on the real view.
3. **Reguli** on Laptop Radu: keep only the demo rules enabled:
   - „Client neservit (demo 10 s)” on Masa 1 → Telegram
   - „Foc în imagine” (cooldown 30 s)
   - turn off „Masă ocupată” and anything noisy; on **Laptop coleg 1** every rule stays off.
4. Staff: only **Marius** is enrolled (via `/angajat-nou`, in the **purple hoodie** he wears for the demo).
   Live labels him „angajat”.
5. Server env: `REMIND_S=60` on ingest (a ⏰ reminder every 60 s while nobody arrived).
6. Live → **Configurare → Ascunde**.

## Rehearsal checklist (09:00, then once more after setup)

| # | Who | Action | Pass if |
|---|---|---|---|
| T1 | — | nobody in front of the camera | Live: no open alerts |
| T2 | presenter | with **no alert open**: Reguli → mic: „Anunță-mă dacă apare un urs” → Confirmă; then delete it, again with no alert open | rule active within 5 s |
| T3 | Radu (guest) | sits at Masa 1, nobody comes | „Masa 1 așteaptă de 10 s” on Live **and** in AiveeAlerts within ~15 s; only the „Vezi în aplicație” button, no Preiau |
| T3b | — | nobody comes for 60 s more | „⏰ Încă neservit: Masa 1, de 1 min” as a reply to the alert, then again every 60 s („de 2 min”, …) |
| T4 | Marius (staff) | walks to Masa 1 and stays ≥ 5 s | labelled „angajat”; „Un angajat a ajuns la Masa 1 după …”; the original alert now starts with „✅ Rezolvat · un angajat a ajuns după …” and has no buttons; reminders stop |
| T4b | Radu (guest) | repeat T3, then leaves the table before anyone comes | ~10 s after he leaves: „👋 Clientul a plecat de la Masa 1 fără să fie servit (a așteptat …)”; the original becomes „⚪ Închisă · clientul a plecat” |
| T5 | presenter | phone: `/angajat-nou`, name, 20 s capture of a colleague, Salvează | „Gata, ești recunoscut…”; that colleague becomes „angajat” on Live |
| T6 | presenter | lighter in front of the camera ≥ 5 s | „posibil foc” alert + Telegram |
| T7 | presenter | Metrici | **Așteptare** includes the T4 wait (median and p90) and the alert count; no Reacție / Drum tiles |
| T8 | phone holder | Camere → Telefon 1 → ⋯ → Folosește telefonul → scan QR → Start (landscape) | image on Live within 10 s |

After T5, delete the test profile (no delete button yet: ask the developer on duty).

## Fallbacks

| Failure | Do |
|---|---|
| Camera script stopped | Camere shows „fără imagine” within 60 s; restart the script |
| Venue Wi-Fi down | phone hotspot for the laptop; the server is reachable over 4G |
| Server down | laptop stack + phone on USB, same scenario |
| Live AI misbehaves | narrate with the alert history and Metrici from the rehearsal |

## Do not show

- „Adaugă cameră” on a second location: the server serves one location (`SITE=demo`).
- „Testează pe un clip” on the server: video analysis is off there (503).
- The staff profile list: profiles are global, not per company yet.
- **Rule changes while an alert is open** on that camera: creating, editing, enabling or disabling a rule
  reloads the rules and restarts the camera's engine; the open alert is then never closed and its ⏰ reminders
  keep coming. Change rules only when Live shows no open alert (step 2 of the script is fine: nothing is open
  yet). Fix after the hackathon.

## Known limits (say them as the roadmap)

One location per server; each cloud camera needs a provisioned device account and vision worker;
staff profiles are global; invites are links (no email); a rule reload while an alert is open leaves that
alert open (see "Do not show"). Next: pairing codes, one vision worker for
all cameras, per-location profiles.
