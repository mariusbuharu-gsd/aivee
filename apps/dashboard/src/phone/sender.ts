// The phone-as-camera loop: capture a JPEG and post it at a steady rate, never more than one
// request in flight. A slow network skips frames instead of queueing them, so the server always
// gets the newest picture and the phone never piles up memory.
import { ApiError, type CameraView } from '../api/client';

export type SendStatus = 'sending' | 'reconnecting' | 'stopped';

export interface SenderStats {
  /** Frames the server accepted since start. */
  sent: number;
  /** Ticks dropped because the previous request was still running. */
  skipped: number;
  /** Frames accepted in the last second. */
  fps: number;
}

export interface FrameSenderOptions {
  fps: number;
  /** The current camera picture as a JPEG; null while the camera is not ready. */
  capture: () => Promise<Blob | null>;
  send: (jpeg: Blob) => Promise<void>;
  onStatus?: (status: SendStatus) => void;
  onStats?: (stats: SenderStats) => void;
  /** An error retrying cannot fix (logged out, no right, camera gone or not a cloud one). */
  onFatal?: (error: ApiError) => void;
  now?: () => number;
}

export interface FrameSender {
  start(): void;
  stop(): void;
}

const FATAL = new Set([401, 403, 404, 409]);
const BACKOFF_MIN_MS = 500;
const BACKOFF_MAX_MS = 5000;

/** Frames sent during the second before `now` (timestamps in ms). */
export function sentFps(times: readonly number[], now: number): number {
  return times.filter((t) => now - t < 1000).length;
}

/** Canvas size for a video frame: at most `max` px wide, same aspect ratio. */
export function fitWidth(width: number, height: number, max = 640) {
  if (width <= max) return { width, height };
  return { width: max, height: Math.round((height * max) / width) };
}

/** A cloud camera is fed by frames pushed for its own id (`mqtt-frames://<id>`). */
export function isCloudCamera(c: Pick<CameraView, 'id' | 'source'>): boolean {
  return c.source === `mqtt-frames://${c.id}`;
}

export function createFrameSender(o: FrameSenderOptions): FrameSender {
  const now = o.now ?? (() => Date.now());
  let timer: ReturnType<typeof setInterval> | null = null;
  let inFlight = false;
  let status: SendStatus = 'stopped';
  let sent = 0;
  let skipped = 0;
  let times: number[] = [];
  let backoff = 0;
  let pausedUntil = 0;

  const setStatus = (s: SendStatus) => {
    if (s === status) return;
    status = s;
    o.onStatus?.(s);
  };
  const report = () => {
    const t = now();
    times = times.filter((x) => t - x < 1000);
    o.onStats?.({ sent, skipped, fps: sentFps(times, t) });
  };

  async function tick() {
    if (inFlight) {
      skipped += 1;
      report();
      return;
    }
    if (now() < pausedUntil) return;
    inFlight = true;
    try {
      const jpeg = await o.capture();
      if (!jpeg || timer === null) return;
      await o.send(jpeg);
      if (timer === null) return;
      sent += 1;
      times.push(now());
      backoff = 0;
      setStatus('sending');
      report();
    } catch (e) {
      if (timer === null) return;
      if (e instanceof ApiError && e.status !== undefined && FATAL.has(e.status)) {
        stop();
        o.onFatal?.(e);
        return;
      }
      backoff = Math.min(backoff ? backoff * 2 : BACKOFF_MIN_MS, BACKOFF_MAX_MS);
      pausedUntil = now() + backoff;
      setStatus('reconnecting');
    } finally {
      inFlight = false;
    }
  }

  function start() {
    if (timer !== null) return;
    sent = skipped = backoff = pausedUntil = 0;
    times = [];
    setStatus('sending');
    timer = setInterval(() => void tick(), 1000 / o.fps);
  }

  function stop() {
    if (timer !== null) clearInterval(timer);
    timer = null;
    setStatus('stopped');
  }

  return { start, stop };
}
