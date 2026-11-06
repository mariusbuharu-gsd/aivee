import { describe, expect, it } from 'vitest';
import { maskSource } from './maskSource';

describe('maskSource', () => {
  it('hides the user and password', () => {
    expect(maskSource('rtsp://admin:s3cret@192.168.1.20:8554/stream1')).toBe(
      'rtsp://••••@192.168.1.20:8554/…',
    );
  });

  it('drops the default RTSP port and shortens the path', () => {
    expect(maskSource('rtsp://192.168.1.20:554/Streaming/Channels/101')).toBe(
      'rtsp://192.168.1.20/…',
    );
  });

  it('hides a query string, which can carry credentials too', () => {
    expect(maskSource('http://cam.local/video.cgi?user=a&pwd=b')).toBe('http://cam.local/…');
  });

  it('keeps a bare host as it is', () => {
    expect(maskSource('rtsp://cam.local')).toBe('rtsp://cam.local');
    expect(maskSource('rtsp://cam.local/')).toBe('rtsp://cam.local');
  });

  it('masks a user without a password, and a password with an @ in it', () => {
    expect(maskSource('rtsp://admin@10.0.0.2/live')).toBe('rtsp://••••@10.0.0.2/…');
    expect(maskSource('rtsp://admin:p@ss@10.0.0.2/live')).toBe('rtsp://••••@10.0.0.2/…');
  });

  it('leaves a device index or a file path alone', () => {
    expect(maskSource('0')).toBe('0');
    expect(maskSource('/videos/demo.mp4')).toBe('/videos/demo.mp4');
  });

  it('trims surrounding spaces', () => {
    expect(maskSource('  rtsp://u:p@h/x  ')).toBe('rtsp://••••@h/…');
  });
});
