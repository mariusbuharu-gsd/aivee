# 4. Contracts as the single source of truth

Date: 2026-11-06 · Status: accepted · Decision log: D9

## Context

Edge (Python), ingest (Python), API (Python) and dashboard (TypeScript) exchange the same
messages: rules, zones, alert events, metrics, staff suggestions. Three teams change code in
parallel during a 24-hour hackathon. Hand-copied types would drift within hours.

## Decision

`packages/contracts` holds every shared type as a Pydantic model, plus the MQTT topic builder.

- `make schema` exports JSON Schema to `packages/contracts/schema/`;
- `npm run contracts` generates TypeScript types into `apps/dashboard/src/contracts/`;
- CI regenerates both and fails on `git diff` (drift check).

Contracts change only in a dedicated PR.

## Consequences

- A field renamed in Python breaks the dashboard build instead of the demo.
- Payloads are validated at every boundary (MQTT in, HTTP in) with the same models.
- Changing a contract costs a PR and a regeneration step; this is intentional friction.
