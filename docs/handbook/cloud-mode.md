# Cloud mode — runbook

Cloud mode analyses the video in our cloud instead of on a box in the restaurant. Why and the
rules: [ADR 0011](../adr/0011-cloud-or-edge-analysis.md).

```
restaurant                         AiVee cloud
──────────                         ───────────
camera ──► connector ──RTSP──►  MediaMTX ──► vision (edge pipeline) ──MQTT──► ingest ──► phones
 (RTSP / phone MJPEG)  640 px, 5 fps   │ relays, never records
                                       └──► dashboard live view (WebRTC)
```

## Pieces

| Piece | Where | What it does |
|---|---|---|
| `apps/connector/connector.py` | restaurant PC or router (Python 3 + ffmpeg, or the `apps/connector/Dockerfile` image) | pulls the camera, scales to 640 px at 5 fps, rotates upright, pushes H.264 to MediaMTX with the publish credentials |
| `mediamtx` service | cloud | relays streams; publishing needs `STREAM_PUBLISH_USER/PASSWORD`; reading is open (live view, vision) |
| `vision` service (profile `cloud`, image `apps/edge/Dockerfile`) | cloud | the edge pipeline reading `rtsp://mediamtx:8554/$CAMERA_ID`; publishes the same MQTT events as an edge device |

## Run it locally (phone as the camera)

1. In `.env`, set `STREAM_PUBLISH_USER` and `STREAM_PUBLISH_PASSWORD`
   (letters and digits are safest: `openssl rand -hex 24`).
2. Start or restart the stack so MediaMTX picks up the credentials: `make up`.
3. Start the vision worker: `make cloud-up` (first build takes a few minutes).
4. On the phone, start Android IP Webcam. Then push it:

   ```bash
   make connector SOURCE=http://PHONE_IP:8080/video CAMERA_ID=cam-01 ROTATE=90
   ```

5. Check: `docker compose logs -f vision` shows `metrics fps=…`; the dashboard **Live** page plays
   the camera; alerts arrive as with an edge device.

Stop: `Ctrl+C` on the connector, `make cloud-down`.

`python3 apps/connector/connector.py --print …` prints the ffmpeg command (password hidden)
without running it.

## Settings

Connector and vision read the names in `.env.example` under "Cloud mode": `CLOUD_RTSP_URL`,
`CAMERA_ID`, `CLOUD_FPS`, `CLOUD_WIDTH`, `CLOUD_BITRATE_KBPS`, plus `ROTATE` for the connector.
The vision worker uses the edge's MQTT identity (`MQTT_EDGE_USER/PASSWORD`, `SITE`).

## Limits today

- One `vision` service runs one camera. More cameras need more services until the per-camera
  supervisor lands (roadmap, Phase 1/5).
- One shared publish credential. Per-camera keys come with device pairing (P1.5) and stream tokens (P1.6).
- Plain RTSP. Use RTSPS (MediaMTX TLS) for any deployment outside a local network.
- Measured locally with a synthetic 5 fps stream: the worker reaches about 3 fps on a laptop CPU.
  Measure on the real cloud host before sizing (Q33).
