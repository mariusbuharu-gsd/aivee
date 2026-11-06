import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import { FRAME, createFrameSender, isCloudCamera, isPortrait, letterbox, sentFps } from './sender';

const blob = () => new Blob(['x'], { type: 'image/jpeg' });

/** A promise the test resolves or rejects by hand. */
function deferred() {
  let resolve!: () => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<void>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('createFrameSender', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('sends at the target rate while every request answers in time', async () => {
    const send = vi.fn(async () => undefined);
    const s = createFrameSender({ fps: 5, capture: async () => blob(), send });
    s.start();
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(5);
    s.stop();
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(5);
  });

  it('keeps one request in flight and skips frames instead of queueing them', async () => {
    const pending = deferred();
    const send = vi.fn(() => pending.promise);
    const capture = vi.fn(async () => blob());
    const onStats = vi.fn();
    const s = createFrameSender({ fps: 5, capture, send, onStats });
    s.start();
    await vi.advanceTimersByTimeAsync(1000); // the first request hangs for a whole second
    expect(send).toHaveBeenCalledTimes(1);
    expect(capture).toHaveBeenCalledTimes(1); // no capture while waiting either
    expect(onStats).toHaveBeenLastCalledWith(expect.objectContaining({ sent: 0, skipped: 4 }));

    pending.resolve();
    await vi.advanceTimersByTimeAsync(200);
    expect(send).toHaveBeenCalledTimes(2); // the next tick sends again, the backlog is gone
    expect(onStats).toHaveBeenLastCalledWith(expect.objectContaining({ sent: 2, skipped: 4 }));
    s.stop();
  });

  it('reports a passing failure as reconnecting and recovers on the next success', async () => {
    const statuses: string[] = [];
    let fail = true;
    const send = vi.fn(async () => {
      if (fail) throw new ApiError('Serverul nu răspunde.', 'network');
    });
    const s = createFrameSender({
      fps: 5,
      capture: async () => blob(),
      send,
      onStatus: (st) => statuses.push(st),
    });
    s.start();
    await vi.advanceTimersByTimeAsync(200);
    expect(statuses.at(-1)).toBe('reconnecting');
    fail = false;
    await vi.advanceTimersByTimeAsync(1000); // backs off, then tries again
    expect(statuses.at(-1)).toBe('sending');
    s.stop();
    expect(statuses.at(-1)).toBe('stopped');
  });

  it('stops for good on an error retrying cannot fix (401, 403, 404, 409)', async () => {
    const onFatal = vi.fn();
    const send = vi.fn(async () => {
      throw new ApiError('Trebuie să vă autentificați.', 'unauthenticated', 401);
    });
    const s = createFrameSender({ fps: 5, capture: async () => blob(), send, onFatal });
    s.start();
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    expect(onFatal).toHaveBeenCalledWith(expect.objectContaining({ status: 401 }));
  });

  it('skips a tick when the camera gives no frame yet', async () => {
    let ready = false;
    const send = vi.fn(async () => undefined);
    const s = createFrameSender({ fps: 5, capture: async () => (ready ? blob() : null), send });
    s.start();
    await vi.advanceTimersByTimeAsync(400);
    expect(send).not.toHaveBeenCalled();
    ready = true;
    await vi.advanceTimersByTimeAsync(200);
    expect(send).toHaveBeenCalledTimes(1);
    s.stop();
  });
});

describe('sentFps', () => {
  it('counts the frames sent in the last second', () => {
    expect(sentFps([100, 900, 1500, 1800, 1999], 2000)).toBe(3);
    expect(sentFps([], 2000)).toBe(0);
  });
});

describe('letterbox', () => {
  it('fills the 640x360 frame with a 16:9 landscape video', () => {
    expect(letterbox(1280, 720)).toEqual({ x: 0, y: 0, width: 640, height: 360 });
    expect(letterbox(1920, 1080)).toEqual({ x: 0, y: 0, width: 640, height: 360 });
  });

  it('fits a portrait phone video whole, centered between black side bars', () => {
    // 720x1280 → 202.5x360, centered: nothing is cropped
    expect(letterbox(720, 1280)).toEqual({ x: 218.75, y: 0, width: 202.5, height: 360 });
  });

  it('puts bars above and below a video wider than 16:9', () => {
    expect(letterbox(1280, 480)).toEqual({ x: 0, y: 60, width: 640, height: 240 });
  });

  it('keeps a 4:3 video whole with side bars', () => {
    expect(letterbox(640, 480)).toEqual({ x: 80, y: 0, width: 480, height: 360 });
  });

  it('always outputs the fixed frame size', () => {
    expect(FRAME).toEqual({ width: 640, height: 360 });
  });
});

describe('isPortrait', () => {
  it('is a video taller than wide', () => {
    expect(isPortrait(720, 1280)).toBe(true);
    expect(isPortrait(1280, 720)).toBe(false);
    expect(isPortrait(0, 0)).toBe(false);
  });
});

describe('isCloudCamera', () => {
  it('is a camera fed by pushed frames for its own id', () => {
    expect(isCloudCamera({ id: 'cam-01', source: 'mqtt-frames://cam-01' })).toBe(true);
    expect(isCloudCamera({ id: 'cam-01', source: 'mqtt-frames://cam-02' })).toBe(false);
    expect(isCloudCamera({ id: 'cam-01', source: 'rtsp://10.0.0.5/stream' })).toBe(false);
  });
});
