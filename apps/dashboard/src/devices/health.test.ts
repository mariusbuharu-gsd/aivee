import { describe, expect, it } from 'vitest';
import type { CameraView, DeviceView } from '../api/client';
import { cameraHealth, HEALTH_LABEL } from './health';

const NOW = Date.parse('2026-11-23T12:00:00Z');
const ago = (s: number) => new Date(NOW - s * 1000).toISOString();

const cam = (over: Partial<CameraView> = {}): CameraView => ({
  id: 'cam-01',
  name: 'Sala',
  source: 'rtsp://x',
  device: 'edge-01',
  online: true,
  ...over,
});
const dev = (over: Partial<DeviceView> = {}): DeviceView => ({
  device: 'edge-01',
  state: 'online',
  last_seen: ago(3),
  ...over,
});

describe('cameraHealth', () => {
  it('follows the device when the API has no per-camera signal', () => {
    expect(cameraHealth(cam(), dev(), NOW)).toEqual({ state: 'online', cause: null });
    expect(cameraHealth(cam(), dev({ state: 'offline' }), NOW)).toEqual({
      state: 'offline',
      cause: 'device',
    });
    // No devices poll yet: the camera list's `online`.
    expect(cameraHealth(cam({ online: false }), null, NOW).state).toBe('offline');
    expect(cameraHealth(cam(), dev({ last_seen: ago(120) }), NOW)).toEqual({
      state: 'stale',
      cause: 'device',
    });
  });

  it('tells one dead camera apart from a dead device', () => {
    const two = [
      cam({ id: 'a', last_frame_at: ago(2), stream_state: 'ok' }),
      cam({ id: 'b', last_frame_at: ago(300), stream_state: 'down' }),
    ];
    expect(two.map((c) => cameraHealth(c, dev(), NOW))).toEqual([
      { state: 'online', cause: null },
      { state: 'offline', cause: 'camera' },
    ]);
  });

  it('shows a reconnecting stream, and an old last frame as offline', () => {
    expect(cameraHealth(cam({ stream_state: 'reconnecting' }), dev(), NOW).state).toBe(
      'reconnecting',
    );
    expect(cameraHealth(cam({ last_frame_at: ago(90) }), dev(), NOW)).toEqual({
      state: 'offline',
      cause: 'camera',
    });
    expect(cameraHealth(cam({ last_frame_at: null }), dev(), NOW).state).toBe('offline');
  });

  it('a dead device wins over a stale camera signal', () => {
    expect(
      cameraHealth(
        cam({ stream_state: 'ok', last_frame_at: ago(1) }),
        dev({ state: 'offline' }),
        NOW,
      ),
    ).toEqual({ state: 'offline', cause: 'device' });
  });

  it('labels every state in Romanian', () => {
    expect(HEALTH_LABEL.offline).toBe('Cameră offline');
    expect(HEALTH_LABEL.reconnecting).toBe('Se reconectează…');
  });
});
