import { describe, expect, it, vi } from 'vitest';
import { captureBurst, fitLongSide, shotCount } from './burst';

describe('fitLongSide', () => {
  it('keeps portrait and landscape aspect, long side 640', () => {
    expect(fitLongSide(1080, 1920)).toEqual({ width: 360, height: 640 });
    expect(fitLongSide(1920, 1080)).toEqual({ width: 640, height: 360 });
    expect(fitLongSide(480, 640)).toEqual({ width: 480, height: 640 });
  });
});

describe('captureBurst', () => {
  it('takes a shot every 1.5 s for 20 s: 14 shots, 13 waits', async () => {
    expect(shotCount(20)).toBe(14);
    const sleep = vi.fn(async () => undefined);
    const onShot = vi.fn();
    const shots = await captureBurst({
      seconds: 20,
      grab: async () => new Blob(['x'], { type: 'image/jpeg' }),
      sleep,
      onShot,
    });
    expect(shots).toHaveLength(14);
    expect(sleep).toHaveBeenCalledTimes(13);
    expect(sleep).toHaveBeenCalledWith(1500);
    expect(onShot).toHaveBeenLastCalledWith(14);
  });

  it('skips frames the video could not give and stops when aborted', async () => {
    const ctrl = new AbortController();
    let n = 0;
    const shots = await captureBurst({
      seconds: 20,
      grab: async () => {
        n++;
        if (n === 4) ctrl.abort();
        return n % 2 ? new Blob([String(n)]) : null;
      },
      sleep: async () => undefined,
      signal: ctrl.signal,
    });
    expect(n).toBe(4);
    expect(shots).toHaveLength(2);
  });
});
