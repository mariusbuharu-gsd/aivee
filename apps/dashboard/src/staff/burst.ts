// One phone takes the photos itself: a JPEG every ~1.5 s for ~20 s while the employee turns.

export const SHOT_INTERVAL_MS = 1500;
export const MAX_SIDE = 640;
export const JPEG_QUALITY = 0.8;

/** Scale (width, height) so the long side is at most `max`, keeping the aspect ratio. */
export function fitLongSide(width: number, height: number, max = MAX_SIDE) {
  const long = Math.max(width, height);
  if (long <= max) return { width, height };
  const k = max / long;
  return { width: Math.round(width * k), height: Math.round(height * k) };
}

/** How many shots fit in `seconds` at one every `intervalMs`, the first at 0. */
export function shotCount(seconds: number, intervalMs = SHOT_INTERVAL_MS): number {
  return Math.floor((seconds * 1000 - 1) / intervalMs) + 1;
}

const realSleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/**
 * Grab a frame every `intervalMs` for `seconds`. A grab that gives nothing (video not ready)
 * is skipped. Stops early when `signal` aborts; resolves with the frames taken so far.
 */
export async function captureBurst({
  seconds,
  grab,
  intervalMs = SHOT_INTERVAL_MS,
  sleep = realSleep,
  onShot,
  signal,
}: {
  seconds: number;
  grab: () => Promise<Blob | null>;
  intervalMs?: number;
  sleep?: (ms: number) => Promise<void>;
  onShot?: (taken: number) => void;
  signal?: AbortSignal;
}): Promise<Blob[]> {
  const shots: Blob[] = [];
  const n = shotCount(seconds, intervalMs);
  for (let i = 0; i < n && !signal?.aborted; i++) {
    const blob = await grab();
    if (blob) {
      shots.push(blob);
      onShot?.(shots.length);
    }
    if (i < n - 1) await sleep(intervalMs);
  }
  return shots;
}

/** The video's current frame as a JPEG, long side ≤ MAX_SIDE, aspect kept (never cropped). */
export function grabJpeg(
  video: HTMLVideoElement | null,
  canvas: HTMLCanvasElement,
): Promise<Blob | null> {
  if (!video || video.readyState < 2 || !video.videoWidth) return Promise.resolve(null);
  const { width, height } = fitLongSide(video.videoWidth, video.videoHeight);
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) return Promise.resolve(null);
  ctx.drawImage(video, 0, 0, width, height);
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY));
}
