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

## Cameră în cloud prin HTTPS

Where only HTTPS (443) reaches the cloud, as on the GSD swarm behind nginx/Traefik
(`app-aivee.earth.sv.gsd.com.ro`), the connector sends JPEG frames instead of RTSP. The RTSP
path above stays as it is.

```
laptop / phone ──► connector --push ──HTTPS POST──► api ──MQTT frames/<cam>──► vision (SOURCE=mqtt-frames://<cam>)
                   640 px, 5 fps JPEG               │ newest frame in memory, never on disk
                                                    └──► GET /api/cameras/<cam>/live.mjpg ──► dashboard <img>
```

- The connector POSTs each frame to `/api/ingest/frames/<camera_id>` over one keep-alive
  connection, with HTTP Basic `STREAM_PUBLISH_USER/PASSWORD`. When the server is slow it drops
  frames (it never queues them); on errors it backs off from 1 s to 30 s. It logs
  `push fps=… sent=… dropped=…` every 10 s.
- The API keeps the newest frame per camera **in memory only**, never on disk, and relays it on
  `Topics.frames` of the camera's device (QoS 0, not retained). **Single api replica only:**
  with two replicas, the live view may not see the frames.
- The vision worker reads them with `SOURCE=mqtt-frames://<camera_id>` and its own MQTT identity
  (ACL `pattern read aivee/+/%u/frames/#`). A pause in the upload is a stream gap like any
  other (`stream_gap seconds=…` in the log).
- The dashboard live view (Live tile, zone editor's „Folosește imaginea live”) still tries
  WebRTC first. When that fails, or when the camera's source is `mqtt-frames://…`, it shows
  `live.mjpg` in an `<img>`. Detection boxes overlay as before.
- One credential for now: the shared publish credential is the MediaMTX one. Per-device keys
  replace it after the freeze (P1.5–P1.6).

### What the server needs

1. The camera exists, attached to the vision worker's device. In the dashboard: **Dispozitive**
   → add a camera, under the technical details set **Id cameră** `cam-coleg-1` and **Dispozitiv**
   the worker's MQTT user (e.g. `edge-01`). Set the source to `mqtt-frames://cam-coleg-1` so the
   live view goes straight to MJPEG. Draw its zones and rules as usual.
2. One vision service per camera, with `SOURCE=mqtt-frames://cam-coleg-1`,
   `CAMERA_ID=cam-coleg-1`, `ROTATE=0` and the worker's `MQTT_EDGE_USER/PASSWORD` (= the
   camera's device). It needs no MediaMTX.
3. The api has `STREAM_PUBLISH_USER` and `STREAM_PUBLISH_PASSWORD` set, and the proxy in
   front of it does not buffer `live.mjpg` (the API sends `X-Accel-Buffering: no`; set
   `proxy_buffering off` on that location if the proxy ignores it).
4. Mosquitto has the current `infra/mosquitto/acl` (the `frames/#` read line); the broker
   reads the ACL at start.

### Laptop webcam (a colleague, anywhere)

Needs Python 3.10+ and ffmpeg (`sudo apt install ffmpeg` · `brew install ffmpeg`), and the
repo (or only `apps/connector/connector.py`). The credentials come from the team password
manager, never from chat.

```bash
export STREAM_PUBLISH_USER=...        # password manager: AiVee stream publish
export STREAM_PUBLISH_PASSWORD=...
python3 apps/connector/connector.py --source 0 --camera-id cam-coleg-1 \
  --push https://app-aivee.earth.sv.gsd.com.ro
```

`--source 0` is the first webcam: `/dev/video0` (v4l2) on Linux, avfoundation device 0 on
macOS. Options: `CLOUD_FPS` (default 5), `CLOUD_WIDTH` (640), `CLOUD_JPEG_QUALITY` (6, 2 = best),
`--rotate 90|180|270`. `--print` shows the ffmpeg command without running it. Stop with Ctrl+C.
`HTTP 404` in the log means the camera does not exist in the cloud yet (step 1 above);
`HTTP 401` means wrong credentials.

### Phone (Android IP Webcam)

Start IP Webcam on the phone, then on a laptop in the same Wi-Fi:

```bash
python3 apps/connector/connector.py --source http://PHONE_IP:8080/video --rotate 90 \
  --camera-id cam-coleg-1 --push https://app-aivee.earth.sv.gsd.com.ro
```

`--rotate 90` sends a phone held upright the right way up.

### Bandwidth

About **1 Mbps upload per camera** at 5 fps, 640 px, quality 6 (measured: ~23 KB per frame on
a busy test picture; a real room is usually smaller). That is more than the RTSP H.264 path
(~0.4 Mbps): plain JPEGs are the price of passing through port 443. Lower `CLOUD_FPS` or
`CLOUD_WIDTH` on a weak uplink.

### Latency

Measured on localhost (`apps/api/tests/test_frames_e2e_integration.py`, real Mosquitto with
the real ACL): POST → vision worker has the decoded frame, median ~4 ms; POST → `live.mjpg` part,
median ~2 ms. Over the internet add the upload time of one ~25 KB frame plus one round trip.

## Settings

Connector and vision read the names in `.env.example` under "Cloud mode": `CLOUD_RTSP_URL`,
`CLOUD_PUSH_URL`, `CAMERA_ID`, `CLOUD_FPS`, `CLOUD_WIDTH`, `CLOUD_BITRATE_KBPS`,
`CLOUD_JPEG_QUALITY`, plus `ROTATE` for the connector.
The vision worker uses the edge's MQTT identity (`MQTT_EDGE_USER/PASSWORD`, `SITE`).

## Limits today

- One `vision` service runs one camera. More cameras need more services until the per-camera
  supervisor lands (roadmap, Phase 1/5).
- One shared publish credential (RTSP and HTTPS frames alike). Per-camera keys come with device pairing (P1.5) and stream tokens (P1.6).
- HTTPS frames live in the api process: one api replica only.
- Plain RTSP. Use RTSPS (MediaMTX TLS) for any deployment outside a local network.
- Measured locally with a synthetic 5 fps stream: the worker reaches about 3 fps on a laptop CPU.
  Measure on the real cloud host before sizing (Q33).
