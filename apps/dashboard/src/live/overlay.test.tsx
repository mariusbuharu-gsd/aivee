import { act, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CameraView, Detection } from '../api/client';
import { HttpApi } from '../api/http';
import { CameraTile } from '../components/CameraTile';
import { fakeApi, renderWithApi } from '../test/fakeApi';

class FakeSocket {
  static last: FakeSocket | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(readonly url: string) {
    FakeSocket.last = this;
  }
  close() {}
  emit(m: unknown) {
    this.onmessage?.({ data: JSON.stringify(m) });
  }
}

afterEach(() => vi.unstubAllGlobals());

describe('HttpApi.subscribeDetections', () => {
  it('parses detections frames for its camera only', () => {
    vi.stubGlobal('WebSocket', FakeSocket);
    const seen: Detection[][] = [];
    const off = new HttpApi('http://api:8000').subscribeDetections('cam-01', (d) => seen.push(d));
    const ws = FakeSocket.last as FakeSocket;
    expect(ws.url).toBe('ws://api:8000/ws/events');
    const item = {
      track_id: 3,
      role: 'guest',
      box: [0.1, 0.1, 0.2, 0.3],
      staff_score: 0.1,
      raised_hand: true,
    };
    ws.emit({ type: 'detections', camera_id: 'cam-02', data: [item] });
    ws.emit({ type: 'alert', data: {} });
    ws.emit({ type: 'detections', camera_id: 'cam-01', data: 'garbage' });
    ws.emit({ type: 'detections', camera_id: 'cam-01', data: [item, { track_id: 'x' }] });
    expect(seen).toEqual([[{ ...item, box: [0.1, 0.1, 0.2, 0.3] }]]);
    off();
  });
});

describe('CameraTile overlay', () => {
  const camera: CameraView = {
    id: 'cam-01',
    name: 'Sala',
    source: 'rtsp://x',
    zones: [],
    device: 'edge-01',
    online: true,
  };

  it('draws staff, guests and a raised hand with Romanian labels', () => {
    let push: (d: Detection[]) => void = () => undefined;
    const api = fakeApi({
      subscribeDetections: vi.fn((_id: string, cb: (d: Detection[]) => void) => {
        push = cb;
        return () => undefined;
      }),
    });
    renderWithApi(<CameraTile camera={camera} />, api);
    act(() =>
      push([
        { track_id: 7, role: 'staff', box: [0.1, 0.2, 0.1, 0.4], staff_score: 0.9 },
        { track_id: 12, role: 'guest', box: [0.5, 0.4, 0.1, 0.3], raised_hand: true },
      ]),
    );
    const staff = screen.getByText('angajat #7').parentElement as HTMLElement;
    expect(staff).toHaveClass('det', 'det-staff');
    expect(staff).not.toHaveClass('det-hand');
    expect(staff.style.left).toBe('10%');
    const guest = screen.getByText('mână ridicată #12').parentElement as HTMLElement;
    expect(guest).toHaveClass('det-guest', 'det-hand');
    expect(screen.getByText(/2 persoane/)).toBeInTheDocument();
  });
});
