# 10. "Arrived" is detected on the edge, not self-reported

Date: 2026-11-06 · Status: accepted · Decision log: D23

## Context

The owner's real questions are "how long did the guest wait" and "how fast did we react". The
lifecycle is opened → acknowledged ("Merg eu") → arrived → closed. An "am ajuns" button would be
easy to build, but a busy waiter forgets to press it, or presses it from the bar, and then the
numbers lie.

## Decision

- `acknowledged` is a user action: "Merg eu" in the dashboard (`POST /api/alerts/{event_id}/ack`,
  409 once someone took it or once it is closed).
- `arrived` is an edge event (`AlertEvent.state = "arrived"`): the situation engine emits it once per
  open alert when a track with the role `staff` keeps its foot point inside the alert's zone for at
  least `ARRIVE_S` seconds (default 5). Walking past does not count, and does not count as staff
  presence for the rule's conditions either.
- `arrived` may come without `acknowledged`; it is shown as "fără preluare".
- Ingest folds the times onto the opened event's row; the API derives
  wait = arrived (or closed) − opened, reaction = acknowledged − opened,
  travel = arrived − acknowledged, and `/api/metrics/service` returns the median and p90 of each.
- Ingest sends a second Telegram message on arrival ("Ana a ajuns la Masa 4 după 2 min 10 s").

Code: `apps/edge/src/aivee_edge/domain/engine.py`, `domain/zone_state.py`, `apps/api/src/aivee_api/alerts/`.

## Consequences

- The times measure what the camera saw, not what someone tapped, so they can go into a report.
- Arrival depends on the role classifier: a waiter misread as a guest does not arrive, and the alert
  stays open until its condition clears. Owner confirmation of staff (ADR 5) reduces this.
- `ARRIVE_S` trades delay for certainty: every measured wait includes those 5 s.
- An edge that goes offline cannot report arrival or close; handling open alerts on device offline is
  in progress (`fix/alert-edge-cases`).
