# IP cameras on one edge device (TP-Link Tapo and other RTSP cameras)

How to run several real RTSP cameras on one edge device (a laptop or an edge box), check them,
and see when one is down. The example is two TP-Link Tapo cameras on one laptop. Edge modes in
general: [edge-modes.md](edge-modes.md).

## 1. Prepare each Tapo camera

1. **Camera Account.** In the Tapo app: the camera → ⚙ **Settings** → **Advanced Settings** →
   **Camera Account**. Create a user name and password. This account is
   only for RTSP/ONVIF; it is not your TP-Link cloud login. Use letters and digits: a `;`, `@`,
   `:`, `/` or a space in the password would have to be percent-encoded in the URL
   (`%3B`, `%40`, `%3A`, `%2F`, `%20`).
2. **Third-party compatibility (newer firmware).** On recent firmware RTSP is off until you
   turn it on: **Me** → **Tapo Lab** → **Third-Party Compatibility** → on. Without it the
   camera refuses the RTSP login even with the right account.
3. **Fixed IP.** In the router, add a DHCP reservation for each camera's MAC address (for
   example `192.168.1.21` and `192.168.1.22`). The edge reads the cameras by IP; a lease that
   changes after a reboot looks like a dead camera.
4. **Streams.** Every Tapo camera serves two RTSP streams on port 554 (ONVIF on port 2020):

   | URL | What | Use |
   |---|---|---|
   | `rtsp://USER:PASS@IP:554/stream1` | main stream, full resolution (1080p to 2K and more) | not for detection (unless set to 720p, below) |
   | `rtsp://USER:PASS@IP:554/stream2` | substream, 640×360 or 1280×720 depending on the model | **detection** |

   Detection runs on the **substream** (audit 3.1). YOLO resizes every frame to 640 px
   anyway, so a 2K picture only costs decoding time (one decoder thread per camera) and
   memory, and makes the laptop fall behind with two cameras. If your model's substream is
   only 640×360 and people at the far tables are too small, set the main stream to 720p
   in the app (**Video Quality**) and use `/stream1`, rather than a 2K main stream.

Tapo cameras accept only a few RTSP sessions at a time. The edge, `make camera-check`, VLC and
the Tapo app's own live view each take one; close what you do not need.

## 2. Configure the cameras: `CAMERAS`

Credentials go **only in `.env`** (gitignored) or `edge.env` on a device, never in a commit,
a chat or the dashboard. In the repo's `.env`:

```bash
# one line; <camera id>=<url>, separated by ";"
CAMERAS=cam-01=rtsp://USER:PASS@192.168.1.21:554/stream2;cam-02=rtsp://USER:PASS@192.168.1.22:554/stream2
```

- The ids are the camera ids the dashboard and the rules use (letters, digits, `-`, `_`).
- Entries may also be separated by whitespace or newlines.
- **`SOURCE` wins over `CAMERAS`.** When `SOURCE` is set (env or `--source`), the edge runs that
  one camera and logs `CAMERAS ignored`. This keeps the cloud `vision` worker, `make edge
  SOURCE=…`, `mqtt-frames://` and offline clip runs working as before. For a CAMERAS run,
  leave `SOURCE` out of `.env`.
- `CAMERAS` cannot be combined with `CLIP_EPOCH` or `PROGRESS_FILE` (offline clip runs).
- `ROTATE` and `TARGET_FPS` apply to every camera. A Tapo mounted upside down is flipped in
  the Tapo app (**Image Flip**), not with ROTATE.
- On a device with `infra/edge/compose.yml`, the same line goes into `edge.env`; one `edge`
  service runs all cameras (`docker compose -f compose.yml up -d --remove-orphans`).

## 3. Check the cameras: `make camera-check`

```bash
make camera-check                       # every camera in CAMERAS from .env
make camera-check CHECK_SECONDS=15      # longer, steadier fps
```

For each camera it opens the stream the way the edge does (RTSP over TCP, 5 s timeouts) for
about 8 seconds and prints, with the password masked:

```
OK   cam-01  rtsp://USER:***@192.168.1.21:554/stream2  1280x720  15.0 fps  first frame 1.20 s  codec h264
FAIL cam-02  rtsp://USER:***@192.168.1.22:554/stream2  no frame within 8 s
```

The exit code is 1 when any camera fails. A stream larger than 1080p gets a hint to use the
substream. `fps` is counted after the start-up burst (FFmpeg decodes its probe backlog
quickly at first). You can also pass URLs: `uv run python tools/camera_check.py
cam-01=rtsp://…`, but they then stay in the shell history.

When a camera fails: ping its IP, check the Camera Account and Third-Party Compatibility,
check that the URL path is `/stream2`, and close other RTSP viewers.

## 4. Run two cameras locally (laptop = edge box)

Once, on a fresh checkout (see the [README quickstart](../../README.md#quickstart)):

```bash
cp .env.example .env     # fill in the MQTT_* users and passwords (MQTT_EDGE_USER, e.g. edge-01),
                         # POSTGRES_*; `make keys` adds the API keys
make dev && make data-dirs
uv run python tools/download_models.py   # edge models into models/
```

An existing `.env` from the demo setup already has all of this; a worktree links it
(`ln -s ../aivee/.env .env`, see [the docs index](../README.md)).

Add `CAMERAS=…` to `.env` (section 2) and check it (section 3). Then:

```bash
make up            # Mosquitto, Postgres, migrations, MediaMTX, ingest ×2, API on :8000
make seed          # demo org, location `demo`, owner@aivee.demo (DEMO_PASSWORD in .env)
cd apps/dashboard && npm ci && VITE_API_URL=http://localhost:8000 npm run dev   # another terminal
```

In the dashboard (`http://localhost:5173/intra`, log in as `owner@aivee.demo`):
**Camere** → **Adaugă cameră** once per camera. Under the technical details, **Id cameră** must
be the id from `CAMERAS` (`cam-01`, `cam-02`) and **Dispozitiv** the edge's device id
(`DEVICE`, by default `MQTT_EDGE_USER`, i.e. `edge-01`). In **Adresa sursei** put the URL
**without the password** (`rtsp://192.168.1.21:554/stream2`): the edge reads the real URL from
`CAMERAS`, and the dashboard's copy is stored in Postgres and sent over MQTT.

Then start the edge, in its own terminal:

```bash
make edge-cameras  # every camera in CAMERAS, one process, one MQTT connection
```

The log shows one `edge started … camera=cam-01 source=rtsp://USER:***@…` line per camera,
`metrics fps=…` per camera every 5 s, and a `camera_health` summary every minute. Draw the
zones per camera (**Camere → Editează zonele**) and add rules per camera (**Reguli**). Rules and
zones reach the edge within a second, no restart needed.

**Live video in the dashboard** comes from MediaMTX (WebRTC at `:8889/<camera id>`); the
edge does not publish video. To see a Tapo camera live, relay its substream into the local
MediaMTX (needs `STREAM_PUBLISH_USER/PASSWORD` in `.env`), one terminal per camera:

```bash
ffmpeg -rtsp_transport tcp -i "rtsp://USER:PASS@192.168.1.21:554/stream2" -c copy -f rtsp \
  -rtsp_transport tcp "rtsp://PUBLISH_USER:PUBLISH_PASS@localhost:8554/cam-01"
```

The edge can then read `rtsp://localhost:8554/cam-01` instead of the camera, so the camera
serves a single RTSP session. Without the relay the live page shows the boxes over a
placeholder, and the zone editor uses the last alert snapshot as its background.

## 5. When a camera goes down

The capture adapter reads each camera on its own thread and keeps only the newest frame, so a
camera never builds up lag. It reconnects with exponential backoff (0.5 s up to 10 s), and
reports its health every second:

| Log line | Meaning |
|---|---|
| `camera_reconnecting camera=cam-02` | the stream dropped or an open failed; retrying |
| `camera_down camera=cam-02 last_frame_age_s=61` | no frame for more than 60 s |
| `camera_up camera=cam-02` | frames again |
| `camera_health cam-01=ok fps=15.0 size=1280x720 age_s=0.1 cam-02=down …` | every minute |

What the dashboard shows today, without a contract change:

- The device's metrics combine all its cameras, because the API keeps one `Metrics` per
  device. `fps` is the **slowest** camera's, and a camera that sent nothing for 15 s counts as
  0, so one dark camera shows as `FPS 0.0` on the camera cards (**Detalii tehnice**).
- When **every** camera of the device is dark, metrics stop and after 60 s the cards turn to
  „fără imagine”, as with a single camera.
- One camera down never stops the others. A pipeline that crashes is logged
  (`camera_failed`) and restarted after 5 s.

A per-camera „Cameră offline” needs a per-camera field in the contracts (see the open items
in the edge PR); the edge already computes it (`aivee_edge.health`, state `ok` /
`reconnecting` / `down`, `last_frame_at`, `fps`).

## 6. Cost of each camera

Each camera has its own capture thread, detector, pose model and visual scorer (the ByteTrack
tracker lives in the detector, so they cannot be shared). The CLIP weights for appearance and
visual rules are loaded once per process and shared.

- **Memory**: measured on the reference laptop, the first camera's detector + pose takes the
  process to about 530 MB (OpenVINO and torch runtimes); each further camera adds only a few
  MB for its models plus its frames. CLIP, when appearance or a visual rule is on, adds about
  0.6 GB once.
- **CPU** is the limit: every camera runs its own inference at `TARGET_FPS`. In a local test on
  an i7-1355U laptop (two synthetic 720p RTSP streams, nobody in view so pose never ran, other
  work on the machine), both cameras held 8–10 fps with system CPU at about 90 %. People in view
  add pose inference per frame. Measure on the real machine with real cameras; with more
  cameras, lower `TARGET_FPS` (5 is enough for waiting-time rules) before adding hardware.
  Batched inference across cameras is on the roadmap (audit 3.2.6).
