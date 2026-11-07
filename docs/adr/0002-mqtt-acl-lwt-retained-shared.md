# 2. MQTT with ACL, LWT, retained state and shared subscriptions

Date: 2026-11-06 · Status: accepted · Decision log: D7, D8

## Context

Edges sit behind restaurant routers, reboot, and lose connectivity. The backend must know
which devices are online, push configuration to them, and absorb their events without loss
or duplicates. Plain HTTP polling handles none of this well.

## Decision

Mosquitto is the only link between edge and backend. Topics live under
`aivee/<site>/<device>/…` and are built only through `aivee_contracts.topics.Topics`.

- **ACL per device** (`%u`): an edge user can write only its own device topics.
- **LWT**: `status` is retained with last will `offline`, so a dead edge shows offline at once.
- **Retained complete state**: the API publishes the whole `RuleSet`, `DeviceConfig` and
  `StaffProfiles` on every change. An edge that reconnects gets everything; no diffs.
- **QoS 1** for events, suggestions, snapshots and state; QoS 0 for metrics.
- **Shared subscriptions**: ingest workers subscribe to `$share/ingest/aivee/+/+/events`
  (and `.../suggestions`); the broker load-balances between them. Ingest ignores duplicates.

## Consequences

- Ingest scales horizontally by starting more workers (`docker-compose.yml` runs two).
- Adding a site or device is a new MQTT user and an ACL line, not a code change.
- QoS 1 means at-least-once delivery, so every consumer must be idempotent (covered by
  integration tests).
- The broker is a single point; for the MVP one Mosquitto per deployment is enough.
