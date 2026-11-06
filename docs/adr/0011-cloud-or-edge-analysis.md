# 11. Video analysis in our cloud or on site, per customer

Date: 2026-11-06 · Status: accepted · Refines ADR 0001 · Backlog: I4, Q12, Q31–Q35, Q37

## Context

ADR 0001 runs all vision on one machine per site. That keeps video in the restaurant and works
without internet, but every location then needs a box we have to buy, ship, install and support.
For a small restaurant that box is the main barrier to starting. All of AiVee's other parts
(broker, ingest, API, dashboard) already run in one shared cloud.

The vision code is one pipeline behind `typing.Protocol` ports (`apps/edge/src/aivee_edge/domain/`
is pure), so the same code can read a camera on site or a stream in our cloud.

## Decision

One shared multi-tenant cloud for every customer; a dedicated server only on a custom Enterprise
plan. Where the video is analysed is chosen per location, in one of three modes:

| Mode | On site | Analysis | Leaves the restaurant |
|---|---|---|---|
| **Cloud** | the cameras; where a camera cannot push a stream itself, the connector (`apps/connector/`) on any PC or router | the vision worker in our cloud (`vision` service, image `apps/edge/Dockerfile`) | a small video stream (640 px, 5 fps, ~0.4 Mbps per camera), plus alerts |
| **Edge on the customer's PC** | our vision program on a PC the restaurant already has | on site | alerts and blurred snapshots only |
| **Edge box** (paid extra) | our mini-PC | on site | alerts and blurred snapshots only |

Rules for cloud mode:

- The stream goes into MediaMTX; publishing needs credentials (`infra/mediamtx/entrypoint.sh`).
  Per-camera keys issued by the API replace the shared credential with multi-tenancy (roadmap P1.5–P1.6).
- Frames are analysed in memory and discarded. MediaMTX relays and never records. No video is
  stored anywhere.
- Servers are in the EU; the stream is encrypted in transit (RTSPS) on every non-local deployment.
- When the internet drops, a cloud location gets no alerts; the dashboard shows "locație offline".
  Edge mode is the answer for sites that need alerts without internet (Q17, Q35).
- Cloud mode needs about 5 Mbps upload for four cameras. Below that, we recommend edge (Q32).

## Consequences

- A restaurant can start with only its cameras, the same day. Edge becomes a product option
  instead of a requirement.
- The privacy promise differs per mode and is written that way wherever it appears:
  edge, "video-ul nu pleacă din restaurant"; cloud, "video-ul e analizat și aruncat, nu e salvat
  niciodată, pe servere în UE". Neither may be used for the other mode.
- Cloud mode processes guests' video on our servers: we are a processor for that video, the
  customer is the controller, and a DPIA reviewed by a lawyer is required before a paid cloud
  customer (Q16, Q34).
- We pay compute per camera in the cloud. The cloud price must sit above that cost (Q33).
- **Licences (Q37).** The detector comes from Ultralytics (`apps/edge/pyproject.toml`), which is
  licensed AGPL-3.0, to be verified before launch. Running it as a network service obliges us to
  offer the corresponding source to its users. AiVee's code stays open source (MIT), so we comply
  by publishing the source of what runs in our cloud and showing the licence notice in the app.
  If the code ever closes, cloud mode needs an Ultralytics commercial licence or a permissively
  licensed detector.
- The edge pipeline now has a container image used by all three modes. One service handles one
  camera; a supervisor that starts a worker per camera from the API's configuration comes with
  multi-tenancy.
