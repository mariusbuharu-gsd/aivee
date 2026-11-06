import { act, fireEvent, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LivePlayer } from './LivePlayer';
import { isCloudFrames, pickLiveSource } from './source';

const URL_ = 'http://api.test/api/cameras/cam-1/live.mjpg?location_id=demo';

describe('pickLiveSource', () => {
  it('keeps WebRTC first for a normal camera, exactly as before', () => {
    expect(pickLiveSource({ webRtc: true, whepFailed: false, mjpegUrl: URL_ })).toBe('webrtc');
    expect(pickLiveSource({ webRtc: true, whepFailed: false, mjpegUrl: null })).toBe('webrtc');
  });

  it('falls back to MJPEG when WebRTC fails or is missing', () => {
    expect(pickLiveSource({ webRtc: true, whepFailed: true, mjpegUrl: URL_ })).toBe('mjpeg');
    expect(pickLiveSource({ webRtc: false, whepFailed: false, mjpegUrl: URL_ })).toBe('mjpeg');
  });

  it('shows the placeholder when neither can play (mock API, no MJPEG)', () => {
    expect(pickLiveSource({ webRtc: true, whepFailed: true, mjpegUrl: null })).toBe('placeholder');
    expect(pickLiveSource({ webRtc: false, whepFailed: false, mjpegUrl: null })).toBe(
      'placeholder',
    );
  });

  it('sends a cloud-frames camera straight to MJPEG', () => {
    expect(
      pickLiveSource({ webRtc: true, whepFailed: false, mjpegUrl: URL_, cloudFrames: true }),
    ).toBe('mjpeg');
    expect(isCloudFrames('mqtt-frames://cam-coleg-1')).toBe(true);
    expect(isCloudFrames('rtsp://mediamtx:8554/cam-01')).toBe(false);
    expect(isCloudFrames(undefined)).toBe(false);
  });
});

describe('LivePlayer fallback', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('without WebRTC and without MJPEG keeps the placeholder and no image', () => {
    const { container } = render(<LivePlayer cameraId="cam-1" label="Sala" />);
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('.player')).toHaveAttribute('data-status', 'placeholder');
  });

  it('plays the MJPEG in an <img> and reports playing on load', () => {
    const onStatus = vi.fn();
    const { container } = render(
      <LivePlayer cameraId="cam-1" label="Sala" mjpegUrl={URL_} onStatus={onStatus} />,
    );
    const img = container.querySelector('img');
    if (!img) throw new Error('no <img>');
    expect(img).toHaveAttribute('src', URL_);
    fireEvent.load(img);
    expect(container.querySelector('.player')).toHaveAttribute('data-status', 'playing');
    expect(container.querySelector('.player-placeholder')).toBeNull();
    expect(onStatus).toHaveBeenLastCalledWith('playing');
  });

  it('shows the placeholder when the MJPEG has no frames yet, then retries', () => {
    vi.useFakeTimers();
    const { container } = render(<LivePlayer cameraId="cam-1" label="Sala" mjpegUrl={URL_} />);
    const img = container.querySelector('img');
    if (!img) throw new Error('no <img>');
    fireEvent.error(img);
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('.player')).toHaveAttribute('data-status', 'placeholder');
    act(() => vi.advanceTimersByTime(10_000));
    expect(container.querySelector('img')).toHaveAttribute('src', URL_);
    // the retry stays quiet: still the placeholder until a frame arrives
    expect(container.querySelector('.player')).toHaveAttribute('data-status', 'placeholder');
  });

  it('skips WebRTC for a cloud-frames camera even where WebRTC exists', () => {
    const pc = vi.fn();
    vi.stubGlobal('RTCPeerConnection', pc);
    const { container } = render(
      <LivePlayer cameraId="cam-1" label="Sala" mjpegUrl={URL_} cloudFrames />,
    );
    expect(container.querySelector('img')).toHaveAttribute('src', URL_);
    expect(container.querySelector('video')).toBeNull();
    expect(pc).not.toHaveBeenCalled();
  });
});
