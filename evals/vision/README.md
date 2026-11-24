# Vision eval on real-camera clips

`make eval-vision` runs the edge pipeline offline on labelled clips and reports, per rule kind,
**recall** and **false alerts per labelled hour**. It is the yardstick for every vision change
(thresholds, tracker, pose, a new detector, INT8 calibration): run it before and after.

With no clips it prints how to get some and exits 0.

## 1. Record

Clips and labels live in `recordings/eval/` (gitignored: the frames show guests, so they never go
to git). Record every camera at once:

```bash
export CAM_01_URL='rtsp://…'   # from the password manager, never committed or pasted in docs
export CAM_02_URL='rtsp://…'
make record-cams CAMS="cam-01=$CAM_01_URL cam-02=$CAM_02_URL" SECONDS=600
# → recordings/eval/cam-01-20261124-1930.mp4, recordings/eval/cam-02-20261124-1930.mp4
```

`REC_FPS` (default 15) sets the written frame rate. One camera only: `make record
SOURCE=… SECONDS=600 NAME=eval/cam-01-sala`. Aim for 2-5 minute stretches that contain the
situations (a guest raising a hand, a table left waiting) and long quiet stretches (normal
service), in daylight, evening and crowded hours. Film only with the venue's consent.

## 2. Label

Next to each clip, a JSON file with the same name (`cam-01-20261124-1930.json`):

```json
{
  "camera": {
    "id": "cam-01",
    "name": "Sala",
    "zones": [
      { "id": "t1", "name": "Masa 1", "tag": "table", "polygon": [[0.05, 0.5], [0.3, 0.5], [0.3, 0.8]] },
      { "id": "e1", "name": "Intrare", "tag": "entrance", "polygon": [[0.75, 0.1], [0.95, 0.1], [0.95, 0.4]] }
    ]
  },
  "expected": [
    { "kind": "raised_hand", "zone": "t1", "t_start": 42.0, "t_end": 55.0, "note": "guest by the window" },
    { "kind": "unattended", "zone": "t1", "t_start": 410.0, "t_end": 520.0 }
  ],
  "quiet": [{ "t_start": 0, "t_end": 40 }],
  "fully_labelled": true,
  "tolerance_s": 5
}
```

| Field | Meaning |
|---|---|
| `camera` | `CameraConfig` without `source`: the zones as drawn in the dashboard (copy them from the camera's config). |
| `expected` | Alerts that **should** open: `kind` (below), `zone` (zone id; omit for any zone), and the window `t_start`–`t_end` in clip seconds in which opening is correct. `note` is free text. |
| `quiet` | Segments in which **no** alert of any kind should open. |
| `fully_labelled` | `true` (default): every situation in the clip is in `expected`, so any other alert is false and the whole clip counts as labelled time. `false`: only alerts inside `quiet` count as false, and labelled time is the sum of the `quiet` segments. |
| `tolerance_s` | Slack on both ends of each window (default 5 s). |
| `rules` | Optional list of `Rule` objects (as the API stores them). Default: [`default_rules.json`](default_rules.json), the four table and entrance situations with the product's default timings. |
| `fps` | Optional analysis fps (default `--fps`, 10). |
| `video` | Optional clip file name, if it is not the label's name with `.mp4`/`.mkv`/`.avi`/`.mov`. |

Kinds are derived from a rule's most specific condition:

| `kind` | Rule | Default rule |
|---|---|---|
| `raised_hand` | `pose` | a guest at a table raises a hand |
| `unattended` | `absent` (with `present`) | guests seated ≥ 60 s, no staff for 300 s |
| `not_cleared` | `objects_unattended` | dishes on a table nobody visited for 300 s |
| `queue` | `count` | ≥ 4 guests at the entrance, no staff |
| `object_gone`, `object_present`, `visual`, `present` | the open and other kinds | (label your own `rules`) |

Labelling tips: set `t_start` to when a fair human would page a waiter (e.g. the hand has been up
for a second), `t_end` to when the alert stops being useful (the waiter arrives, the hand goes
down). An alert that re-opens inside the same window after its cooldown is a `repeat`, neither a
hit nor a false alert. Times are clip seconds; a player that shows seconds (mpv, VLC) is enough.

## 3. Run

```bash
make eval-vision                     # recordings/eval/
make eval-vision CLIPS=path/to/clips # another folder
uv run python evals/vision/run.py --help   # --detector, --pose, --fps, --grace-s
```

Models come from `models/` (`tools/download_models.py`). Per clip it prints hits, misses and
false alerts with their mm:ss, then the totals:

```
clips: 6, labelled: 1.50 h
kind             expected  hits  recall  false  false/h
raised_hand            14    12     86%      3      2.0
unattended              5     5    100%      1      0.7
false alerts: 4, per hour: 2.7
```

Appearance scoring is off, as in the default edge, so staff are recognised by behaviour only.

## Files

- `run.py`: drives `EdgePipeline` directly (`FileSource` → YOLO + ByteTrack → pose → roles →
  situation engine) with a static config and a collecting publisher; no MQTT, no API.
- `matcher.py`: pure matching and scoring, unit-tested in `apps/edge/tests/test_eval_vision.py`.
- `default_rules.json`: the rules used when a label has none.

Not yet measured (audit §4.2): alert latency, tracking IDF1 and ID switches, staff/guest
precision, fps and CPU per camera.
