/** "3 s", "14 min", "3 h", "1 zi", "3 zile": how long ago, in a few characters. */
export function sinceRo(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} h`;
  const d = Math.floor(h / 24);
  return d === 1 ? '1 zi' : `${d} zile`;
}

/**
 * The card's freshness line from the device's `last_seen` (refreshed by every status and by
 * the metrics the edge sends every few seconds): "ultima imagine acum 3 s" while online,
 * "offline de 14 min" once it stopped answering. Null when the time is unknown.
 */
export function lastSeenRo(
  online: boolean,
  lastSeen: string | null | undefined,
  now: number,
): string | null {
  const at = lastSeen ? Date.parse(lastSeen) : NaN;
  if (Number.isNaN(at)) return null;
  const since = sinceRo(now - at);
  return online ? `ultima imagine acum ${since}` : `offline de ${since}`;
}

/** An "online" device that has sent nothing for longer than this is shown as "fără imagine". */
export const STALE_MS = 60_000;

export type CameraState = 'online' | 'stale' | 'offline';

/**
 * What the card shows. The API has no per-camera "last frame" time (the `/frame` still is the
 * latest alert snapshot), so the device's `last_seen` stands in: for an edge box it moves with
 * every metrics message, for a cloud camera with what its sender posts. Unknown time = trust
 * `online`.
 */
export function cameraState(
  online: boolean,
  lastSeen: string | null | undefined,
  now: number,
): CameraState {
  if (!online) return 'offline';
  const at = lastSeen ? Date.parse(lastSeen) : NaN;
  return !Number.isNaN(at) && now - at > STALE_MS ? 'stale' : 'online';
}
