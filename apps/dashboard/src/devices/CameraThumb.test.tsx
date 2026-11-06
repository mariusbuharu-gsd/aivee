import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CameraFrame } from '../api/client';
import { ApiContext } from '../api/context';
import { fakeApi } from '../test/fakeApi';
import { CameraThumb, FRAME_REFRESH_MS } from './CameraThumb';

function frame(n: number, release = vi.fn()): CameraFrame {
  return { url: `data:image/png;base64,${n}`, at: new Date().toISOString(), release };
}

/** IntersectionObserver that reports what `visible` says when told to. */
function stubObserver() {
  let cb: IntersectionObserverCallback = () => undefined;
  class IO {
    constructor(c: IntersectionObserverCallback) {
      cb = c;
    }
    observe() {}
    disconnect() {}
  }
  vi.stubGlobal('IntersectionObserver', IO);
  return (visible: boolean) =>
    act(() => cb([{ isIntersecting: visible } as IntersectionObserverEntry], {} as never));
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('CameraThumb', () => {
  it('waits until the card is on screen, then refreshes at most every 30 s', async () => {
    vi.useFakeTimers();
    const show = stubObserver();
    const firstRelease = vi.fn();
    const captureFrame = vi
      .fn()
      .mockResolvedValueOnce(frame(1, firstRelease))
      .mockResolvedValue(frame(2));
    render(
      <ApiContext.Provider value={fakeApi({ captureFrame })}>
        <CameraThumb cameraId="cam-1" name="Sala" online />
      </ApiContext.Provider>,
    );
    expect(captureFrame).not.toHaveBeenCalled();
    await show(true);
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(captureFrame).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('img', { name: /Captură de la Sala/ })).toHaveAttribute(
      'src',
      'data:image/png;base64,1',
    );

    await act(() => vi.advanceTimersByTimeAsync(FRAME_REFRESH_MS - 1));
    expect(captureFrame).toHaveBeenCalledTimes(1);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(captureFrame).toHaveBeenCalledTimes(2);
    expect(firstRelease).toHaveBeenCalled(); // the old blob URL is freed
    expect(FRAME_REFRESH_MS).toBeGreaterThanOrEqual(30_000);

    await show(false); // scrolled away: no more requests
    await act(() => vi.advanceTimersByTimeAsync(FRAME_REFRESH_MS * 3));
    expect(captureFrame).toHaveBeenCalledTimes(2);
  });

  it('loads at once where IntersectionObserver is missing', async () => {
    vi.stubGlobal('IntersectionObserver', undefined);
    const captureFrame = vi.fn().mockResolvedValue(frame(1));
    render(
      <ApiContext.Provider value={fakeApi({ captureFrame })}>
        <CameraThumb cameraId="cam-1" name="Sala" online={false} />
      </ApiContext.Provider>,
    );
    expect(await screen.findByRole('img', { name: /Captură de la Sala/ })).toBeInTheDocument();
  });
});
