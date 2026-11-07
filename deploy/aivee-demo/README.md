# AiVee on the GSD develop swarm (`aivee-demo`)

The shared test server: colleagues open the dashboard from their own laptops, get an account and
connect their laptop webcam as a camera. Approved by Marius for the develop swarm; it shares the
cluster with every other dev project, so touch only `aivee-demo_*` services and volumes.

Internal names are placeholders here: `REGISTRY` (the image registry), `SWARM_MANAGER` (ssh host of
the swarm manager), `DB_NODE` (the node the stateful services are pinned to), `OTHER_NODE`. The real
values are in the team's infrastructure notes.

## URLs and services

| URL | Service | What |
|---|---|---|
| https://aivee.earth.sv.gsd.com.ro | `site` | presentation site (`apps/site`, static nginx) |
| https://app-aivee.earth.sv.gsd.com.ro | `dashboard` | production build; nginx proxies `/api/`, `/ws/`, `/healthz` to `api` on the same origin, so the session cookie needs no CORS |
| wss://mqtt-aivee.earth.sv.gsd.com.ro (path `/mqtt`) | `mosquitto` :9001 | MQTT over WebSockets for remote edges (needs the nginx block below) |

| Service | Image | Notes |
|---|---|---|
| `postgres` | `pgvector/pgvector:pg17` | volume `aivee-demo_pg-data` |
| `mosquitto` | `aivee/mosquitto` | `infra/mosquitto` entrypoint + ACL, `mosquitto.conf` here (1883 internal, 9001 websockets); accounts api, ingest, `edge-01`, `edge-coleg-1..3`, `edge-telefon-1..2` (`MQTT_EXTRA_DEVICES`) |
| `api` | `aivee/api` (`ml` extra: staff enrolment) | `SITE=demo`, `DEVICE=edge-01`, `COOKIE_SECURE=true` |
| `ingest` | `aivee/ingest` | 1 replica, `TELEGRAM_POLL=false` |
| `dashboard`, `site` | `aivee/dashboard`, `aivee/site` | nginx:alpine |
| `vision-cam-coleg-1..3`, `vision-cam-telefon-1..2` | `aivee/vision` | `vision.yml`: cloud vision workers, see "Rules on the server" |

All pinned to `DB_NODE`: the database, the broker's retained state and the snapshots volume
(shared by api and ingest) live there, and OTHER_NODE crashes now and then. Traefik routes by the
`traefik.http.routers.aivee-demo-*` labels on `traefik-network`; the stack's own overlay is
`aivee-demo_internal`. MediaMTX is not deployed (see Known limits).

Registry: `REGISTRY/aivee/<image>:<git sha8>`. Images are built on a laptop (the
manager has no GitHub key).

## Files

| Here | On the manager (`~/aivee-demo/`) |
|---|---|
| `stack.yml` | `stack.yml` (copy; keep the two the same) |
| `vision.yml` | `vision.yml` (deployed only once cloud frames are on develop) |
| `run-once.sh` | `run-once.sh`: migrate / seed as one-off swarm tasks |
| `build.sh` | (laptop only) builds and pushes the images |
| `mosquitto.Dockerfile`, `mosquitto.conf`, `vision.Dockerfile` | (baked into the images) |
| `nginx-aivee.conf` | proposal for `/etc/nginx/sites-available/aivee.conf` (not installed) |
| — | `aivee.env`: every secret, mode 600, never in git |

`aivee.env` holds (names only): `POSTGRES_DB/USER/PASSWORD`, `MQTT_API_*`, `MQTT_INGEST_*`,
`MQTT_EDGE_USER/PASSWORD` (edge-01), `EDGE_COLEG_1..3_PASSWORD`, `EDGE_TELEFON_1..2_PASSWORD`, `MQTT_EXTRA_DEVICES`,
`VAPID_PUBLIC_KEY/PRIVATE_KEY/SUBJECT`, `DEMO_PASSWORD`, `PUBLIC_DASHBOARD_URL`,
`ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`. The generated values are
the server's own (not the laptop's). Read one without printing the file:
`grep ^DEMO_PASSWORD= ~/aivee-demo/aivee.env | cut -d= -f2-`.

## Deploy and update

```bash
# 1. Laptop, from a clean checkout of the commit to ship (tag = git sha8):
deploy/aivee-demo/build.sh                    # all images; or: build.sh api dashboard
df -h /mnt/data                               # on the manager first, if pushing a lot (Nexus blobs)

# 2. Manager: copy the stack files if they changed
scp deploy/aivee-demo/{stack.yml,vision.yml,run-once.sh} SWARM_MANAGER:aivee-demo/

# 3. Manager, ~/aivee-demo:
TAG=<sha8> ./run-once.sh migrate              # when a migration was added (before the api update)
TAG=<sha8> docker stack deploy --with-registry-auth -c stack.yml aivee-demo
```

`docker stack deploy` sets every `aivee/*` image to `TAG`. To move a single service instead:

```bash
docker service update --with-registry-auth --image REGISTRY/aivee/api:<sha8> aivee-demo_api
docker service inspect aivee-demo_api --format '{{.Spec.TaskTemplate.ContainerSpec.Image}}'
```

The `--image` flag is required: swarm pins the digest at creation, so `--force` alone re-runs
the old image. A later `docker stack deploy` puts every service back on its `TAG`, so keep
`TAG` = what is running.

First deploy only (already done 2026-11-06, tag `e09080cd`):

```bash
TAG=<sha8> docker stack deploy --with-registry-auth -c stack.yml aivee-demo
TAG=<sha8> ./run-once.sh migrate
TAG=<sha8> ./run-once.sh seed                 # owner@ / manager@ / staff@aivee.demo, DEMO_PASSWORD
docker service update --force aivee-demo_api && docker service update --force aivee-demo_ingest
```

`run-once.sh` starts `aivee-demo_once-<name>` from the api image on `aivee-demo_internal`
(DB_NODE, `--restart-condition none`), waits, prints its log and removes it. A one-off task
rather than migrating on api start: one run, a clear exit code, never two replicas migrating.

## Logs, status, rollback, teardown

```bash
docker service ls --filter label=com.docker.stack.namespace=aivee-demo
docker stack ps aivee-demo --no-trunc
docker service logs -f --tail 100 aivee-demo_api      # _ingest, _mosquitto, _dashboard, ...
docker service rollback aivee-demo_api                # previous spec (image) of one service
TAG=<previous sha8> docker stack deploy --with-registry-auth -c stack.yml aivee-demo   # all of them
```

Teardown (removes the services and the network; the data stays in the volumes on DB_NODE):

```bash
docker stack rm aivee-demo
# Data too, after the tasks are gone (ssh DB_NODE). Only these four, never a prune:
docker volume rm aivee-demo_pg-data aivee-demo_mosquitto-data aivee-demo_snapshots aivee-demo_videos
```

## A colleague's camera on the server

### 1. In the dashboard (owner or manager)

1. Give the colleague an account: **Echipă** → invite (role `manager` to let them add cameras and
   rules), send the invite link. Or share `owner@aivee.demo` for a quick test.
2. **Dispozitive → Adaugă cameră**: Nume (e.g. "Laptop Ana"), Adresa sursei `0`; open the technical
   section and set **Id cameră** `cam-coleg-1` and **Dispozitiv** `edge-coleg-1` (2 → `cam-coleg-2` /
   `edge-coleg-2`, 3 → `cam-coleg-3` / `edge-coleg-3`). Only at location `demo` ("Terasa demo"): the
   API adds cameras at its own `SITE`.
3. **Editează zonele**: draw Masa 1 / Masa 2 (tag `table`) and Intrare (`entrance`) on what the
   webcam sees. Until the camera has sent a frame there is no still to draw on; draw roughly and fix
   later.
4. **Reguli**: write the rule in Romanian (e.g. "Anunță-mă dacă la o masă stau clienți de un minut și
   nu a venit nimeni") → Confirmă și salvează. The API publishes the camera, zones and rules as
   retained MQTT state for `edge-coleg-1`.

Same via the API (what the end-to-end check did): `POST /api/cameras?location_id=demo`
`{id, name, source: "0", device: "edge-coleg-1", zones: [...]}`, then `POST /api/rules`.

### 2. Rules on the server (option A, main flow once cloud frames are on develop)

The colleague runs only the connector, which posts JPEG frames over HTTPS to the api; a
`vision-cam-coleg-<n>` service on DB_NODE runs the rules, and the dashboard shows the live
view (MJPEG). Deploy the workers with the vision image:

```bash
MODELS=~/…/aivee/models deploy/aivee-demo/build.sh vision        # laptop
TAG=<sha8> VISION_TAG=<sha8> docker stack deploy --with-registry-auth \
  -c stack.yml -c vision.yml aivee-demo                          # manager
```

The connector command for colleagues comes with that change (`apps/connector`).

### 3. Edge on the colleague's laptop (option B, needs the nginx block)

The whole pipeline runs on their laptop, built-in webcam `SOURCE=0`; only MQTT goes to the server.

```bash
git clone git@github.com:mariusbuharu-gsd/aivee.git && cd aivee
make dev                                        # uv + Python 3.12
uv run python tools/download_models.py          # models/ (YOLO OpenVINO INT8, YuNet)
cat > .env <<'EOF'
MQTT_HOST=mqtt-aivee.earth.sv.gsd.com.ro
MQTT_PORT=443
MQTT_TRANSPORT=websockets
MQTT_TLS=true
MQTT_WS_PATH=/mqtt
SITE=demo
MQTT_EDGE_USER=edge-coleg-1
MQTT_EDGE_PASSWORD=<from Marius: EDGE_COLEG_1_PASSWORD in ~/aivee-demo/aivee.env>
CAMERA_ID=cam-coleg-1
EOF
chmod 600 .env
make edge SOURCE=0
```

No webcam or models: `make fake-edge SCENARIO=unattended SPEED=10` with the same `.env` runs the
scripted scene against the colleague's camera. One account = one running edge or vision worker at
a time: two clients with the same account share an MQTT client id and keep kicking each other off.

## Known limits

- **WebSockets through the manager's nginx.** The shared `*.earth.sv.gsd.com.ro` block proxies with
  HTTP/1.0 and drops `Upgrade`, so `/ws/events` answers 404 and `wss://mqtt-aivee…` 502. Straight to
  Traefik (`127.0.0.1:8288` on the manager) both upgrade (101). Without the fix the dashboard
  works but shows new alerts and live boxes only on reload, and option B cannot connect.
  Fix: `nginx-aivee.conf` (its own server block for `app-aivee` and `mqtt-aivee`, like
  `gsd-os-hub.conf`; the shared block stays as it is). Marius installs it with sudo; commands in
  the file.
- **Telegram polling off.** The laptop's ingest already long-polls the same bot (one `getUpdates`
  caller per bot, a second gets 409), so "Conectează Telegram" never completes and "Preiau ✋" does
  nothing on the server. Sending works once the location has a chat id (none is set yet, so the
  server sends no Telegram; Web Push works). For both: a second bot, its token and username in
  `aivee.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`), remove `TELEGRAM_POLL: "false"` from
  `stack.yml`, redeploy.
- **Video upload off.** The clip runner runs the edge inside the api, which the slim image does not
  have; without `MQTT_UPLOAD_PASSWORD` `POST /api/videos` answers 503. Staff photo enrolment
  answers 503 too (no `ml` extra). Both need `API_UV_EXTRAS="--extra ml"` plus models in the api
  image (~2.6 GB).
- **No MediaMTX.** WebRTC needs UDP and publishing needs RTSP :8554; the edge path is HTTP(S)
  only. The dashboard falls back to the placeholder with the detection boxes (over `/ws/events`,
  so after the nginx fix). Live video comes with the cloud frames MJPEG view.
- Login rate limit and the metrics cache are in the api process: a restart clears them.
