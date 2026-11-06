# 1. Edge-first CPU inference with OpenVINO

Date: 2026-11-06 · Status: accepted · Decision log: D6

## Context

Restaurants already have cameras but no GPU, no spare bandwidth and no wish to send video
of their guests to a cloud. Alerts must arrive within seconds, also when the internet is slow.

## Decision

All vision runs on one edge machine per site, on the CPU:

- YOLO11n exported to OpenVINO INT8 for people and objects, every frame, tracked with ByteTrack;
- YOLO pose only for people inside table zones;
- a CLIP appearance embedding at most once every 2 s per person (off by default, `--appearance`);
- faces blurred on the device before a snapshot leaves it.

The edge publishes events, metrics and blurred snapshots over MQTT. Video stays on site
(live view goes through MediaMTX on the same network).

## Consequences

- Measured on an i7-1355U laptop: about 20 FPS detection, about 12 FPS with pose; the phone stream
  delivers 8–11 FPS in practice, so the camera, not the model, is the limit.
- No GPU and no per-frame cloud cost; detection and rule evaluation need no internet.
- Model choice is bounded by CPU budget: larger detectors or per-frame CLIP are not an option.
- Each site needs one small x86 box; scaling means more boxes, not a bigger server (see ADR 2).
