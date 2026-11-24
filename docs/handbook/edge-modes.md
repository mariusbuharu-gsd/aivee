# Edge modes: customer PC and edge box — runbook

Two of the three analysis modes in [ADR 0011](../adr/0011-cloud-or-edge-analysis.md) run the vision
pipeline in the restaurant. Both use the same image (`apps/edge/Dockerfile`) and the same
on-site compose file (`infra/edge/compose.yml`). Only the machine differs.

| | Edge on the customer's PC | Edge box |
|---|---|---|
| Machine | a PC the restaurant already has, x86, always on | our mini-PC, shipped preconfigured |
| Who installs | the customer or the installer, following this page | us (pilot) or the CCTV installer |
| What we support | the software | the software and the hardware (replaced if it fails) |
| Video | stays in the restaurant | stays in the restaurant |

## What the machine needs

- x86-64 CPU (no GPU), Docker with the compose plugin, always on, on the same network as the cameras.
- Measured on an i7-1355U laptop: about 20 FPS detection, 12 FPS with pose (ADR 0001). The
  reference edge box and its camera limit are still to be chosen (Q15, O6).
- Outbound internet to the AiVee broker (MQTT). No inbound port is opened.

## Install

1. Copy `infra/edge/compose.yml` and `infra/edge/edge.env.example` to a folder on the machine.
2. Put the models in `models/` next to them (`uv run python tools/download_models.py` on a
   development machine, then copy the folder).
3. Load the image: `docker load < aivee-edge.tar` (built with
   `docker build -f apps/edge/Dockerfile -t aivee-edge:dev .` and `docker save`), until we
   publish it to a registry.
4. `cp edge.env.example edge.env` and fill in the broker address, this device's MQTT credential
   and the location id. No cameras: they are added in the dashboard (**Camere → Caută camere**,
   password, **Testează**; see [ip-cameras.md](ip-cameras.md)). `CAMERAS` or `SOURCE` in
   `edge.env` are dev overrides that win over the dashboard.
5. `docker compose -f compose.yml up -d --remove-orphans` (host networking, for discovery), then
   `docker compose -f compose.yml logs -f` should show `edge box started`, then one
   `camera_started` line per camera added in the dashboard and `metrics fps=…`. The device
   appears online on the dashboard's **Dispozitive** page.

## INT8 calibration on venue frames

The INT8 models are quantised (NNCF) on calibration images. `tools/download_models.py` uses
`coco128.yaml` (128 COCO images) for the detector and `coco8-pose.yaml` for pose by default; both
download automatically. COCO is not a restaurant at night through a dome camera, so before a pilot
calibrate on the venue's own cameras (no labels needed):

1. Record 5-10 minutes per camera across the day, crowded and quiet, lights on and dimmed:
   `make record-cams CAMS="cam-01=$CAM_01_URL cam-02=$CAM_02_URL" SECONDS=600` (clips land in
   `recordings/eval/`, see [evals/vision/README.md](../../evals/vision/README.md)).
2. Re-export INT8 from those clips, one frame every 2 s (300+ frames is what ultralytics recommends):

   ```bash
   uv run python tools/download_models.py --calib-clips recordings/eval/*.mp4 --calib-every-s 2 --force-int8
   ```

   Or from a folder of frames you picked yourself: `--calib-frames recordings/calib/`. Other datasets:
   `--calib-data my.yaml` (detector) and `--calib-pose-data my-pose.yaml` (pose), any ultralytics
   dataset YAML.
3. `--force-int8` replaces `models/*_int8_openvino_model/`; the FP32 exports and `.pt` weights stay.
   Check the result with `make eval-vision` on labelled clips before and after, and keep the old
   folders until it is at least as good.

Frames contain guests: keep them on the machine, out of git (`recordings/` is gitignored), and delete
them when the export is done.

## Limits today

- The device credential is created by hand in the broker. Pairing with a one-time code from the
  dashboard comes with roadmap P1.5.
- MQTT to the cloud is plain TCP. TLS for edge devices comes with P1.6; until then use edge mode
  only inside a trusted network or over a VPN.
- No local alarm in the room yet when the internet drops (Q17, P3.6); events are buffered only in
  memory (P2.3).
- No automatic updates yet (P5.6).
