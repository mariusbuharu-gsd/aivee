# Demo runbook — Astra Hack, Sat 2026-11-07

The presenter script is `docs/demo-script.md`. This file is the operational side: what runs
where, the rehearsal checklist, fallbacks, and what not to show.

## What runs where

| Piece | Where | Who starts it |
|---|---|---|
| Dashboard, api, ingest, vision workers | GSD swarm, `https://app-aivee.earth.sv.gsd.com.ro` (stack `aivee-demo`) | always on |
| Demo camera **Laptop coleg 1** (`cam-coleg-1`) | presenter laptop webcam → connector script → server | presenter, in **their own terminal** (not an agent session) |
| Phone camera **Telefon 1** (`cam-telefon-1`) | any phone → `/telefon?camera=cam-telefon-1`, held **landscape** | the phone holder |
| Telegram | bot `@aivee_sibiu_bot`, group **AiveeAlerts**, polled by the **server** ingest | always on |
| Backup | laptop stack (`make up`, api, dashboard, `make edge-usb`) with the phone on USB | presenter, only if the server or Wi-Fi fails |

Accounts: `owner@aivee.demo`, `manager@aivee.demo`, `staff@aivee.demo` (password `DEMO_PASSWORD` in
`~/aivee-demo/aivee.env` on the manager; never in chat or docs).

The laptop stack shares the bot, so its `.env` has `TELEGRAM_POLL=false`: only one poller per bot.

## Before 10:30 (setup, ~15 min)

1. Start the camera script on the presenter laptop; check **Live → Laptop coleg 1** shows the room.
2. **Camere → Laptop coleg 1 → Editează zonele**: draw **Masa 1** (table) and **Intrare** on the real view.
3. **Reguli** on Laptop coleg 1: keep only the demo rules enabled:
   - „Masă neservită” 20–30 s on Masa 1 → Telegram
   - „Foc în imagine” (cooldown 30 s)
   - turn off „Masă ocupată” and anything noisy.
4. Staff: only **Vasi – personal** exists. Vasi wears the black jacket.
5. Live → **Configurare → Ascunde**.

## Rehearsal checklist (09:00, then once more after setup)

| # | Who | Action | Pass if |
|---|---|---|---|
| T1 | — | nobody in front of the camera | Live: no open alerts |
| T2 | presenter | Reguli → mic: „Anunță-mă dacă apare un urs” → Confirmă | rule active within 5 s |
| T3 | guest | sits at Masa 1, nobody comes | alert on Live **and** in AiveeAlerts within the rule time + 5 s |
| T4 | staff | presses **Preiau ✋** in Telegram, walks to Masa 1 | Telegram shows who took it; staff labelled „angajat”; alert closes by itself |
| T5 | presenter | phone: `/angajat-nou`, name, 20 s capture of a colleague, Salvează | „Gata, ești recunoscut…”; that colleague becomes „angajat” on Live |
| T6 | presenter | lighter in front of the camera ≥ 5 s | „posibil foc” alert + Telegram |
| T7 | presenter | Metrici | shows the T3 wait and the T4 reaction |
| T8 | phone holder | Camere → Telefon 1 → ⋯ → Folosește telefonul → scan QR → Start (landscape) | image on Live within 10 s |

After T5, delete the test profile (no delete button yet: ask the developer on duty).

## Fallbacks

| Failure | Do |
|---|---|
| Camera script stopped | Camere shows „fără imagine” within 60 s; restart the script |
| Venue Wi-Fi down | phone hotspot for the laptop; the server is reachable over 4G |
| Server down | laptop stack + phone on USB, same scenario (Preiau does not work there while the server polls the bot) |
| Live AI misbehaves | narrate with the alert history and Metrici from the rehearsal |

## Do not show

- „Adaugă cameră” on a second location: the server serves one location (`SITE=demo`).
- „Testează pe un clip” on the server: video analysis is off there (503).
- The staff profile list: profiles are global, not per company yet.

## Known limits (say them as the roadmap)

One location per server; each cloud camera needs a provisioned device account and vision worker;
staff profiles are global; invites are links (no email). Next: pairing codes, one vision worker for
all cameras, per-location profiles.
