// Which picture a live view shows. WebRTC (MediaMTX WHEP) first, as before; when it cannot
// play, the API's MJPEG of the frames a connector posts over HTTPS (cloud mode behind 443).
// A camera whose source is `mqtt-frames://…` has no WebRTC stream at all, so it skips the try.

export type LiveSource = 'webrtc' | 'mjpeg' | 'placeholder';

export const CLOUD_FRAMES_SCHEME = 'mqtt-frames://';

export const isCloudFrames = (source: string | null | undefined): boolean =>
  !!source?.startsWith(CLOUD_FRAMES_SCHEME);

export function pickLiveSource({
  webRtc,
  whepFailed,
  mjpegUrl,
  cloudFrames = false,
}: {
  /** The browser has WebRTC and the view wants live video. */
  webRtc: boolean;
  /** The WHEP attempt for this camera failed. */
  whepFailed: boolean;
  /** `GET /api/cameras/{id}/live.mjpg`, null when the API has none (mock mode). */
  mjpegUrl: string | null | undefined;
  cloudFrames?: boolean;
}): LiveSource {
  if (webRtc && !whepFailed && !(cloudFrames && mjpegUrl)) return 'webrtc';
  return mjpegUrl ? 'mjpeg' : 'placeholder';
}
