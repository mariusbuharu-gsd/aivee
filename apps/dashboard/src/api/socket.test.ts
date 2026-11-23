import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SharedSocket, backoffMs } from './socket';

class FakeSocket {
  static all: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  onmessage: ((e: MessageEvent<string>) => void) | null = null;
  closed = false;
  constructor(readonly url: string) {
    FakeSocket.all.push(this);
  }
  close() {
    this.closed = true;
  }
  open() {
    this.onopen?.();
  }
  drop(code = 1006) {
    this.onclose?.({ code } as CloseEvent);
  }
  send(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent<string>);
  }
}

const parse = (raw: string) => JSON.parse(raw) as { n: number } | null;

beforeEach(() => {
  FakeSocket.all = [];
  vi.stubGlobal('WebSocket', FakeSocket);
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('SharedSocket', () => {
  it('opens one socket for every subscriber and closes it after the last one leaves', () => {
    const s = new SharedSocket('ws://api/ws/events', parse, () => undefined);
    const a = vi.fn();
    const b = vi.fn();
    const offA = s.subscribe(a);
    const offB = s.subscribe(b);
    expect(FakeSocket.all).toHaveLength(1);
    FakeSocket.all[0]?.send({ n: 1 });
    expect(a).toHaveBeenCalledWith({ n: 1 });
    expect(b).toHaveBeenCalledWith({ n: 1 });
    offA();
    expect(FakeSocket.all[0]?.closed).toBe(false);
    offB();
    expect(FakeSocket.all[0]?.closed).toBe(true);
  });

  it('ignores malformed frames', () => {
    const s = new SharedSocket('ws://x', parse, () => undefined);
    const cb = vi.fn();
    s.subscribe(cb);
    FakeSocket.all[0]?.onmessage?.({ data: '{nope' } as MessageEvent<string>);
    expect(cb).not.toHaveBeenCalled();
  });

  it('reconnects with a growing back-off and announces the reconnect, not the first open', () => {
    const s = new SharedSocket('ws://x', parse, () => undefined);
    const again = vi.fn();
    s.onReconnect(again);
    s.subscribe(() => undefined);
    FakeSocket.all[0]?.open();
    expect(again).not.toHaveBeenCalled();

    FakeSocket.all[0]?.drop();
    vi.advanceTimersByTime(backoffMs(0) - 1);
    expect(FakeSocket.all).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.all).toHaveLength(2);
    // Still down: the next try waits longer.
    FakeSocket.all[1]?.drop();
    vi.advanceTimersByTime(backoffMs(0));
    expect(FakeSocket.all).toHaveLength(2);
    vi.advanceTimersByTime(backoffMs(1) - backoffMs(0));
    expect(FakeSocket.all).toHaveLength(3);
    FakeSocket.all[2]?.open();
    expect(again).toHaveBeenCalledTimes(1);
  });

  it('stops on 1008 (no session) and reports it; a later subscriber connects again', () => {
    const unauthorized = vi.fn();
    const s = new SharedSocket('ws://x', parse, unauthorized);
    const off = s.subscribe(() => undefined);
    FakeSocket.all[0]?.drop(1008);
    vi.advanceTimersByTime(60_000);
    expect(unauthorized).toHaveBeenCalledTimes(1);
    expect(FakeSocket.all).toHaveLength(1);
    off();
    s.subscribe(() => undefined);
    expect(FakeSocket.all).toHaveLength(2);
  });

  it('does not reconnect once everybody left', () => {
    const s = new SharedSocket('ws://x', parse, () => undefined);
    const off = s.subscribe(() => undefined);
    FakeSocket.all[0]?.drop();
    off();
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.all).toHaveLength(1);
  });

  it('caps the back-off', () => {
    expect(backoffMs(0)).toBe(1000);
    expect(backoffMs(1)).toBe(2000);
    expect(backoffMs(20)).toBe(15_000);
  });
});
