# New-owner onboarding — audit and plan

Status: **after the freeze** except the items marked *done before freeze*.

## Goal

A restaurant owner with no technical help goes from sign-up to the first real alert on their
phone in one sitting, without typing an RTSP URL, a chat id or a password into a terminal.

## Today's journey and where it breaks

| # | Blocker | Where |
|---|---|---|
| 1 | Cameras can only be added at the API's own `SITE`, not at any location | `apps/api/src/aivee_api/cameras/router.py` |
| 2 | Connecting a camera needs a terminal (edge or connector started by hand) | `apps/edge`, `make edge*` |
| 3 | MQTT and stream credentials are shared and created by hand | `infra/mosquitto/entrypoint.sh` |
| 4 | The owner types an RTSP URL and must match a camera id | `apps/dashboard/src/components/AddCameraForm.tsx` |
| 5 | Telegram needs the numeric group chat id typed by hand | `LocationsPage.tsx`, `tools/telegram_chat_id.py` |
| 6 | Web Push works only over HTTPS | deployment |
| 7 | No setup guide after sign-up; RegisterPage promised "În 10 minute primești prima alertă" | `RegisterPage.tsx` |
| 8 | The rules page starts empty; the zone still image lives only in the browser | `/reguli`, zone editor |

## Target journey

1. Create an account and a location (type: restaurant, terasă, magazin, eveniment).
2. Install the connector (a small box or an app on an always-on PC/phone).
3. Pair it with a 6-digit code or QR shown in the dashboard: the connector gets its own
   per-device MQTT and stream keys.
4. The connector scans the LAN (ONVIF WS-Discovery, UDP 3702) and shows thumbnails.
5. The owner enters the camera password once; the connector resolves the stream through
   ONVIF `GetProfiles`/`GetStreamUri` or a brand template.
6. Pick cameras → suggested zones from a detection pass → adjust.
7. Pick rule templates for the location type.
8. Staff uniform photos.
9. "Conectează Telegram" and/or Web Push → test alert.

## Stream URLs without typing them

ONVIF first; when it fails, brand templates (user fills only IP and password):

| Brand | Main stream | Sub stream (use this, 640×360) |
|---|---|---|
| Hikvision | `rtsp://u:p@IP:554/Streaming/Channels/101` | `/Streaming/Channels/102` |
| Dahua / Imou | `rtsp://u:p@IP:554/cam/realmonitor?channel=1&subtype=0` | `subtype=1` |
| Reolink | `rtsp://u:p@IP:554/h264Preview_01_main` | `h264Preview_01_sub` |
| TP-Link Tapo | `rtsp://u:p@IP:554/stream1` (camera account) | `stream2` |
| Axis | `rtsp://u:p@IP/axis-media/media.amp` | `?resolution=640x360` |
| Uniview | `rtsp://u:p@IP:554/media/video1` | `video2` |
| Ezviz | `rtsp://admin:CODE@IP:554/h264/ch1/main/av_stream` | `sub/av_stream` |

go2rtc already implements ONVIF, Tapo, Xiaomi and UniFi sources; the connector should embed it
rather than reimplement discovery.

## Bandwidth

Edge-side analysis at 640×360 @ 5 fps is roughly 120–300 kbps per camera when streamed to the
cloud (estimate, to be measured); plan 0.5 Mbps per camera.

## Plan

| Order | Change | Blockers |
|---|---|---|
| *done before freeze* | Setup checklist, rule templates per location type, honest sign-up copy | 7, 8 |
| *done before freeze* | One-click "Conectează Telegram" (deep link, bot saves the chat) | 5 |
| 1 | Cameras and devices bound to any location in the API | 1 |
| 2 | Pairing code with per-device MQTT/stream keys, revocable | 3 |
| 3 | go2rtc-based connector: ONVIF discovery, brand templates, thumbnails | 2, 4 |
| 4 | Store the zone still image server-side; suggested zones | 8 |
| 5 | HTTPS by default (managed domain) for Web Push | 6 |
| 6 | Phone as camera: WHIP/WebRTC from the browser | 2 |

## How others do it

Verkada, Eagle Eye, Spot AI, Rhombus, Camect and Agent DVR all ship an on-site box or app that
discovers cameras and asks for credentials once; none ask the customer for a stream URL.
