import type { CameraView, DeviceView } from '../api/client';
import { STALE_MS } from './lastSeen';

export type CameraHealthState = 'online' | 'reconnecting' | 'stale' | 'offline';

export interface CameraHealth {
  state: CameraHealthState;
  /**
   * What is down: the AiVee device (every camera on it goes with it) or this one camera. Null
   * while it sees.
   */
  cause: 'device' | 'camera' | null;
}

/** Short state words for pills and tile badges. */
export const HEALTH_LABEL: Record<CameraHealthState, string> = {
  online: 'online',
  reconnecting: 'Se reconectează…',
  stale: 'fără imagine',
  offline: 'Cameră offline',
};

/**
 * How one camera is doing. Several cameras can share one device, so the device's state alone
 * cannot say which camera stopped. When the API sends the per-camera fields (`stream_state`,
 * `last_frame_at`), they decide; without them every camera follows its device: online, offline,
 * or "fără imagine" when an online device has been silent for over a minute.
 */
export function cameraHealth(
  camera: CameraView,
  device: DeviceView | null | undefined,
  now: number,
): CameraHealth {
  const deviceOnline = device ? device.state === 'online' : camera.online;
  if (!deviceOnline) return { state: 'offline', cause: 'device' };

  if (camera.stream_state === 'down') return { state: 'offline', cause: 'camera' };
  if (camera.stream_state === 'reconnecting') return { state: 'reconnecting', cause: 'camera' };
  if (camera.last_frame_at !== undefined) {
    const at = camera.last_frame_at ? Date.parse(camera.last_frame_at) : NaN;
    if (Number.isNaN(at) || now - at > STALE_MS) return { state: 'offline', cause: 'camera' };
    return { state: 'online', cause: null };
  }

  const seen = device?.last_seen ? Date.parse(device.last_seen) : NaN;
  if (!Number.isNaN(seen) && now - seen > STALE_MS) return { state: 'stale', cause: 'device' };
  return { state: 'online', cause: null };
}
