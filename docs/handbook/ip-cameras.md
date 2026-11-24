# IP cameras on one edge device (TP-Link Tapo and other RTSP cameras)

How a venue's IP cameras get onto its edge device (the AiVee box, or a laptop acting as one),
how to check them, and what happens when one is down. The example is two TP-Link Tapo cameras.
Edge modes in general: [edge-modes.md](edge-modes.md).

The main path needs no `.env`, no typed IP and no RTSP URL: the box is on the venue network,
the owner clicks **Caută camere** in the dashboard, picks a camera, types its user and password,
clicks **Testează**, sees a blurred still and saves (section 2). `CAMERAS` and `SOURCE` remain as
dev overrides (section 3).

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
   example `192.168.1.21` and `192.168.1.22`). The saved camera keeps the IP it was found at;
   a lease that changes after a reboot looks like a dead camera (find it again and edit it).
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

## 2. Add the cameras from the dashboard (main path)

1. **Run the box.** On site: `docker compose -f compose.yml up -d` with `infra/edge/compose.yml`
   and an `edge.env` holding only the broker, the device credential and `SITE` (no cameras).
   On a laptop: `make edge-box`. With neither `SOURCE` nor `CAMERAS` set, the edge connects as
   `MQTT_EDGE_USER`, logs `edge box started … running the cameras the dashboard configures`
   and waits for its retained `DeviceConfig`.
2. **Caută camere.** In **Camere**, the dashboard asks the box (`POST
   /api/devices/{device}/discover`). The box sends an ONVIF WS-Discovery probe on its LAN
   interfaces (Docker, bridge and VPN interfaces are skipped) and, for cameras with ONVIF off,
   checks ports 554 and 2020 on its own /24 networks, in about 5 seconds. Each camera found
   comes with a brand guess (ONVIF name or model, the MAC vendor prefix, or Tapo's ONVIF port
   2020) and its usual RTSP paths, substream first: Tapo `/stream2`, Hikvision
   `/Streaming/Channels/102`, Dahua `/cam/realmonitor?channel=1&subtype=1`, Reolink
   `/h264Preview_01_sub`. Cameras the location already has are marked.
3. **User, password, Testează.** The dashboard builds the URL and asks the box to open it once
   (`POST /api/cameras/test`). The box first asks the camera itself (one RTSP DESCRIBE, Digest or
   Basic login), then grabs one frame over RTSP/TCP within 6 s, blurs the faces and sends back
   a JPEG. The answers:

   | Code | Shown | Usual cause |
   |---|---|---|
   | `camera_auth` | „Utilizator sau parolă greșită pentru cameră.” (+ a Tapo hint) | Tapo: not the Camera Account, or Third-Party Compatibility off (section 1) |
   | `camera_unreachable` | „Camera nu răspunde. Verifică IP-ul și că e în aceeași rețea cu cutia AiVee.” | wrong IP, camera off, another network or VLAN |
   | `camera_no_stream` | „Camera răspunde, dar nu trimite imagine la această adresă…” | wrong path, or the camera's RTSP sessions are all taken (close VLC, the app's live view) |
   | `device_offline` / `device_timeout` | the box is not connected / did not answer in time | box off or offline; try again |

4. **Save.** The camera is stored with its full URL, password included. The API sends it to
   the box in the retained `DeviceConfig`, and the box starts that camera within a second,
   without a restart and without touching the other cameras. Removing a camera or changing its
   URL stops or restarts only that camera.

The password stays in Postgres and the device's retained config. Every API response, the
camera list and the audit log show `rtsp://user:***@…`. To change the IP, edit the camera and
leave the password empty: the `***` that comes back keeps the stored one. Testing a saved camera
(`camera_id`) uses its stored URL, so the dashboard never resends the password. The edge never
logs a camera URL with its password.

Discovery needs the box on the venue LAN: `infra/edge/compose.yml` runs the edge with host
networking, because a bridged container sees only Docker's own network. The cloud vision
workers (`SOURCE=mqtt-frames://…`) never answer discovery or tests (`EDGE_JOBS`, default on only
without `SOURCE`), and the API skips them, and the clip runner, when it picks a location's box.

## 3. Dev override: `CAMERAS`

For development without the dashboard, or a box that must ignore it. Credentials then go
**only in `.env`** (gitignored) or `edge.env`, never in a commit or a chat. In the repo's `.env`:

```bash
# one line; <camera id>=<url>, separated by ";"
CAMERAS=cam-01=rtsp://USER:PASS@192.168.1.21:554/stream2;cam-02=rtsp://USER:PASS@192.168.1.22:554/stream2
```

- When set, `CAMERAS` wins over the dashboard: the edge runs exactly these cameras, as before,
  and takes only their zones from the retained config.
- The ids are the camera ids the dashboard and the rules use (letters, digits, `-`, `_`).
- Entries may also be separated by whitespace or newlines.
- **`SOURCE` wins over `CAMERAS`.** When `SOURCE` is set (env or `--source`), the edge runs that
  one camera and logs `CAMERAS ignored`. This keeps the cloud `vision` worker, `make edge
  SOURCE=…`, `mqtt-frames://` and offline clip runs working as before.
- `CAMERAS` (and the edge box) cannot be combined with `CLIP_EPOCH` or `PROGRESS_FILE` (offline
  clip runs).
- `ROTATE` and `TARGET_FPS` apply to every camera. A Tapo mounted upside down is flipped in
  the Tapo app (**Image Flip**), not with ROTATE.

## 4. Check the cameras by hand: `make camera-check`

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

## 5. Run two cameras locally (laptop = edge box)

Once, on a fresh checkout (see the [README quickstart](../../README.md#quickstart)):

```bash
cp .env.example .env     # fill in the MQTT_* users and passwords (MQTT_EDGE_USER, e.g. edge-01),
                         # POSTGRES_*; `make keys` adds the API keys
make dev && make data-dirs
uv run python tools/download_models.py   # edge models into models/
```

An existing `.env` from the demo setup already has all of this; a worktree links it
(`ln -s ../aivee/.env .env`, see [the docs index](../README.md)). Leave `SOURCE` and `CAMERAS`
out of it. Then:

```bash
make up            # Mosquitto, Postgres, migrations, MediaMTX, ingest ×2, API on :8000
make seed          # demo org, location `demo`, owner@aivee.demo (DEMO_PASSWORD in .env)
make edge-box      # its own terminal: the device `edge-01`, waiting for cameras
cd apps/dashboard && npm ci && VITE_API_URL=http://localhost:8000 npm run dev   # another terminal
```

In the dashboard (`http://localhost:5173/intra`, log in as `owner@aivee.demo`): **Camere** →
**Caută camere**, then user, password, **Testează** and save, once per camera (section 2). The
edge log shows `camera_started camera=… source=rtsp://USER:***@…` per camera, `metrics fps=…`
every 5 s, and a `camera_health` summary every minute. Draw the zones per camera (**Camere →
Editează zonele**) and add rules per camera (**Reguli**). Cameras, rules and zones reach the
edge within a second, no restart needed.

**Live video in the dashboard** comes from MediaMTX (WebRTC at `:8889/<camera id>`); the
edge does not publish video. To see a Tapo camera live, relay its substream into the local
MediaMTX (needs `STREAM_PUBLISH_USER/PASSWORD` in `.env`), one terminal per camera:

```bash
ffmpeg -rtsp_transport tcp -i "rtsp://USER:PASS@192.168.1.21:554/stream2" -c copy -f rtsp \
  -rtsp_transport tcp "rtsp://PUBLISH_USER:PUBLISH_PASS@localhost:8554/cam-01"
```

The camera's URL in the dashboard can then be `rtsp://localhost:8554/cam-01` instead of the
camera, so the camera serves a single RTSP session. Without the relay the live page shows the
boxes over a placeholder, and the zone editor uses the last alert snapshot as its background.

## 6. When a camera goes down

The capture adapter reads each camera on its own thread and keeps only the newest frame, so a
camera never builds up lag. It reconnects with exponential backoff (0.5 s up to 10 s), and
reports its health every second:

| Log line | Meaning |
|---|---|
| `camera_reconnecting camera=cam-02` | the stream dropped or an open failed; retrying |
| `camera_down camera=cam-02 last_frame_age_s=61` | no frame for more than 60 s |
| `camera_up camera=cam-02` | frames again |
| `camera_health cam-01=ok fps=15.0 size=1280x720 age_s=0.1 cam-02=down …` | every minute |

The same state goes onto the device's retained `status` as `camera_health` (one entry per live
camera: `state`, `last_frame_at`, `fps`), at once when a camera changes state and otherwise
once a minute. This works on the edge box, with `CAMERAS` and with a single `SOURCE` camera. Ingest stores the
list (`devices.camera_health`) and `GET /api/cameras` returns each camera's `stream_state` and
`last_frame_at`. On the dashboard:

- A camera whose stream is `down` shows as „Cameră offline” with the camera as the cause,
  even while its device and the other cameras stay online. `reconnecting` shows as
  „Se reconectează…”. The card shows when the last frame arrived.
- A camera of an offline device is `down` too, with the device as the cause.
- A camera the edge reports nothing about (an older edge, a clip, a cloud camera) follows its
  device, as before.
- The device's metrics still combine all its cameras, because the API keeps one `Metrics` per
  device: `fps` is the **slowest** camera's, and a camera that sent nothing for 15 s counts
  as 0, so one dark camera shows as `FPS 0.0` under **Detalii tehnice**.
- One camera down never stops the others. A pipeline that crashes is logged
  (`camera_failed`) and restarted after 5 s.

## 7. Cost of each camera

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
