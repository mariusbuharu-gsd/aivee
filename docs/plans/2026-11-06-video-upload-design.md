# Analizează un video — design (2026-11-06)

An owner or manager uploads a short recorded clip for a location. AiVee runs the same vision
pipeline and rules on it as fast as the CPU allows, and the dashboard (`/video`, "Analiză video")
shows the alerts found, at their position in the clip (mm:ss), with the blurred snapshots.

## Flow

```
dashboard /video ──POST /api/videos──▶ API: store file (VIDEO_DIR), camera video-<id> on device
                                        upload-01 with a copy of a live camera's zones + rules,
                                        row in video_uploads (queued), audit video.uploaded
                                       │
                         VideoQueue (in the API, concurrency 1)
                                       │ publish retained config + rules (upload-01 included)
                                       ▼
          python -m aivee_edge --source <clip> --camera-id video-<id> --clip-epoch <start>
                               --progress-file <id>.progress.json --wait-config 20
             MQTT login MQTT_UPLOAD_USER (= device upload-01, ACL %u), SITE = location
                                       │ events + snapshots, like any edge
                                       ▼
                     ingest: stores and folds them; no notification of any kind
                                       │
       queue: progress from the file → edge exits → wait for ingest to settle → close open
              alerts as video_end at the clip's end → done / failed, audit video.analysed
```

## Decisions

| Topic | Choice | Why |
|---|---|---|
| Times | The edge maps clip position onto a fixed instant: `--clip-epoch` = run start, event `at` = epoch + position. The API stores `clip_epoch`; the timeline shows `at - clip_epoch`. | No contract change (AlertEvent keeps a datetime). A 1970 epoch would put the rows into every "since" query and look like corrupt data. Live cameras keep wall clock. |
| Speed | `FileSource` never sleeps; it samples at `TARGET_FPS` (10) of clip time. The run is CPU-bound (≈ live FPS, ~12 FPS with pose on the i7-1355U, so about 1.2× real time at 10 fps). | Same sampling as live, so rule durations mean the same seconds. |
| Rules and zones | Copied once, at upload, from `copy_from_camera_id` into camera `video-<id>` (new rule ids, same zone ids and tags). The edge gets them through the normal retained `config` / `rules` topics and waits for them (`--wait-config`). | Exactly the live camera's setup at that moment; later edits to the live camera do not change a past analysis. |
| MQTT auth | One more broker user, `MQTT_UPLOAD_USER` (default `upload-01`), reusing the per-device `%u` ACL patterns. All clips share that device; cameras differ. | Mosquitto ACLs cannot match part of a topic level (`upload-+`), so a user per clip would need a password-file rewrite and broker reload per upload. Concurrency 1 makes one device enough. |
| Runner | `VideoQueue` inside the API process (asyncio queue, one worker) runs the edge as a subprocess (`VIDEO_PYTHON`, default the API's interpreter). Progress: the edge's JSON progress file. On API start, `running` clips are failed ("Serverul a repornit…") and `queued` ones re-queued. | No new service. Needs the edge installed next to the API: true for `make api` on the host; the compose API image needs `API_UV_EXTRAS="--extra ml"`. |
| No notifications | Ingest decides by id: device `upload-*` or camera `video-*` → stored and folded, but no push, Telegram, arrival follow-up, verification, re-alert, device note or alert audit; the device going offline closes nothing. Live cameras may not use those ids. | Must hold even if the API row is missing or late. The broker ties the device id to the MQTT user, so a live edge cannot pose as an upload and vice versa. |
| Kept out of live views | Upload alerts are excluded from `/api/alerts`, the WS alert feed, `/api/events`, `/api/metrics/service` (median / p90), `/api/metrics`, `/api/devices`, `/api/cameras`, `/api/rules`. | A clip's waits are not service times; nobody can act on them. |
| End of clip | Alerts still open when the clip ends are closed by the system with `closed_reason: "video_end"`, at `clip_epoch + duration`. | The engine never sees the guest leave. |
| Limits | mp4 / mov / webm, ≤ 200 MB (streamed to disk, refused past the limit), ≤ 2 min (OpenCV probe at upload when available; the run stops a longer clip too). | Demo-sized; keeps the queue short. |

## Endpoints (`devices.manage`)

`POST /api/videos` (multipart `file`, `location_id`, `rotate`, `copy_from_camera_id`) · `GET /api/videos?location_id=` ·
`GET /api/videos/{id}` · `GET /api/videos/{id}/events`. See the backend handbook.

## Known gaps

- Uploads only at the API's own location (`SITE`), like cameras: the upload device has one location.
- Clips and their logs stay in `VIDEO_DIR`; there is no delete endpoint yet.
- The retained `config` / `rules` of `upload-01` grow by one camera per clip (harmless; the edge picks its camera).
- Appearance scoring follows the live `APPEARANCE` setting, so staff are recognised only if profiles exist.
