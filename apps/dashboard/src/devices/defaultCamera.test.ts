import { describe, expect, it } from 'vitest';
import type { CameraView } from '../api/client';
import { defaultCamera } from './defaultCamera';

const cam = (id: string, online: boolean, zones = 0): CameraView =>
  ({
    id,
    name: id,
    online,
    device: 'd',
    zones: Array.from({ length: zones }, (_, i) => ({ id: `z${i}`, name: 'z', polygon: [] })),
  }) as unknown as CameraView;

describe('defaultCamera', () => {
  it('prefers an online camera that has zones or rules', () => {
    const cams = [cam('off', false, 2), cam('bare', true), cam('ready', true, 1)];
    expect(defaultCamera(cams)?.id).toBe('ready');
    expect(
      defaultCamera([cam('off', false), cam('a', true), cam('b', true)], [{ camera_id: 'b' }])?.id,
    ).toBe('b');
  });

  it('falls back to the first online, then the first camera', () => {
    expect(defaultCamera([cam('off', false, 1), cam('on', true)])?.id).toBe('on');
    expect(defaultCamera([cam('x', false), cam('y', false)])?.id).toBe('x');
    expect(defaultCamera([])).toBeUndefined();
  });
});
