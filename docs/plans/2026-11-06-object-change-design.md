# Object change at a table, and a vision check of alerts

"The wine glass disappeared from Masa 1": a guest took it, a waiter cleared it, or something
went missing. The edge spots it cheaply. Then, optionally, a vision model looks at the images
once before anyone is told.

## Why hybrid

- **YOLO on the edge is free and always on**, but noisy. A glass behind an arm or a missed
  detection for one frame looks like a disappearance.
- **A vision model (Claude) is accurate but costs money and seconds.** It must not look at
  every frame.
- So the edge decides *when* something may have happened, and the model is asked *once per
  alert* whether the images show it. The model also writes the Romanian sentence.

## Data flow

```
edge  YOLO objects ─► ZoneState.objects (per class count, 3 s confirm) ─► object_gone holds
      pipeline keeps per zone the last frame that showed every object (the "before")
      opened ─► snapshots/<id>-before (blurred) + snapshots/<id> (after, blurred) + events
ingest  store row (+ before_snapshot_path) ─► task: claim pending ─► wait for the images
        ─► AlertVerifier.verify(rule.prompt_ro, zone, [before, after] | [snapshot], kind)
        ─► store status/summary/model/latency on the alert row ─► notify (or not)
api   AlertView.verification, before_snapshot_url · /api/snapshots/<id>-before (same rights
      as the event) · GET /api/metrics/verification (counts per rule and status) · WS pushes
      the alert again when verified_at moves
dashboard  before/after thumbnails, "Confirmat de AI" / "Neconfirmat" / "Se verifică…"
```

## Edge semantics (`object_gone`)

- An object counts in a zone by its **base**: the bottom-centre of its box, the point that
  sits on the table, like a person's foot point on the floor. `objects_unattended` keeps the
  box centre, unchanged.
- Per class, the *level* is the highest count seen in the last `GONE_CONFIRM_S = 3 s`. A drop
  below level k records the k-th object as gone. So one of two glasses taken counts.
- The object must have been there for `min_duration_s`, and never less than the confirm window.
- **Open/close:** a disappearance is momentary, so the condition is made to last. It holds
  from the moment the object has been missing for 3 s until the object reappears or
  `GONE_HOLD_S = 30 s` pass. The alert therefore opens once, can be taken with "Merg eu" and
  arrived at, and closes by itself (or at once when the glass comes back). The usual
  `cooldown_s` applies. The translator uses 60 s for this situation.

## Verification (every alert kind, `VERIFY_ALERTS`)

- The question comes from the rule's own Romanian text, e.g. «Regula: «Anunță-mă dacă dispare
  un pahar de pe masă». Zona: Masa 1. Imaginea 1 este înainte, imaginea 2 după. A dispărut…?»
  `object_gone` sends before and after; every other kind sends its single opened snapshot.
- The SDK usage is the translator's: `messages.parse` with a Pydantic answer
  (`yes`, `summary_ro`, `object_ro`), effort low, and fixed instructions cached.
- **Notify after the check.** Confirmed: notify with the model's summary. Rejected: no
  notification; the alert stays visible as "Neconfirmat" until the edge closes it.
  Unavailable: notify as a normal alert.
- With the feature off, or without `ANTHROPIC_API_KEY`, every opened alert is stored as
  `unavailable` and notified at once, as before.

## Cost control

- At most one call per alert: `UPDATE … SET verification_status='pending' WHERE … IS NULL`,
  so a second replica or a redelivered event never calls again.
- Edge cooldown per rule and zone, plus the 3 s confirm window, bound the call rate.
- Effort low, two small JPEGs at most, `max_tokens` 1000, cached system prompt.
- Off by default.

## Failure modes

| Failure | Result |
|---|---|
| No key, flag off | `unavailable`, normal alert, no delay |
| Timeout (`VERIFY_TIMEOUT_S`, 20 s), API or connection error, refusal, max_tokens | `unavailable`, logged, normal alert (delayed by up to the timeout) |
| Before or after image did not arrive in 2 s | `unavailable`, normal alert |
| Occlusion makes YOLO think the glass is gone | the model sees it is still there → `rejected`, nobody is disturbed |
| Model wrong on a real event (rejected) | alert still on the dashboard as "Neconfirmat"; measured per rule |
| Ingest restarts during a check | the row stays `pending` and is not retried, and the alert was not notified (accepted for now) |

## Measuring

Every result is on the opened row: `verification_status`, `verification_summary_ro`,
`verification_object_ro`, `verification_model`, `verification_latency_ms`, `verified_at`
(migration `0008`). `GET /api/metrics/verification` returns `{rule_id, status, alerts}`.
rejected / (confirmed + rejected) is the false-alarm rate per rule.
