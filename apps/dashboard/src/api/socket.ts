import type { Unsubscribe } from './client';

const BACKOFF_FIRST_MS = 1_000;
const BACKOFF_MAX_MS = 15_000;

/** Wait before reconnect attempt `n` (0-based): 1 s, 2 s, 4 s … at most 15 s. */
export function backoffMs(n: number): number {
  return Math.min(BACKOFF_MAX_MS, BACKOFF_FIRST_MS * 2 ** n);
}

/**
 * One WebSocket for every subscriber of the page. It opens with the first subscriber, closes
 * after the last one, and reconnects with a growing back-off in between. Whatever happened while
 * it was down is lost, so `onReconnect` callbacks run after every reconnect (not the first
 * open): that is the moment to reload state from the REST API.
 */
export class SharedSocket<M> {
  private ws: WebSocket | null = null;
  private retry: ReturnType<typeof setTimeout> | undefined;
  private attempts = 0;
  private dropped = false;
  private readonly listeners = new Set<(m: M) => void>();
  private readonly reconnects = new Set<() => void>();

  constructor(
    private readonly url: string,
    /** Null (or a throw) skips the frame. */
    private readonly parse: (raw: string) => M | null,
    /** The server closed with 1008: no session. No retry until a new subscriber comes. */
    private readonly onUnauthorized: () => void,
  ) {}

  subscribe(cb: (m: M) => void): Unsubscribe {
    this.listeners.add(cb);
    if (!this.ws && this.retry === undefined) this.connect();
    return () => {
      this.listeners.delete(cb);
      if (this.listeners.size === 0) this.shutdown();
    };
  }

  onReconnect(cb: () => void): Unsubscribe {
    this.reconnects.add(cb);
    return () => this.reconnects.delete(cb);
  }

  private connect() {
    this.retry = undefined;
    const ws = new WebSocket(this.url);
    this.ws = ws;
    ws.onopen = () => {
      this.attempts = 0;
      if (this.dropped) this.reconnects.forEach((cb) => cb());
      this.dropped = false;
    };
    ws.onmessage = (e: MessageEvent<string>) => {
      let m: M | null = null;
      try {
        m = this.parse(e.data);
      } catch {
        return; // malformed frame
      }
      if (m === null || typeof m !== 'object') return;
      this.listeners.forEach((cb) => cb(m));
    };
    ws.onclose = (e: CloseEvent) => {
      if (this.ws !== ws) return; // closed on purpose
      this.ws = null;
      // 1008 = policy violation: the API closes the socket when there is no session.
      if (e.code === 1008) {
        this.dropped = false;
        this.onUnauthorized();
        return;
      }
      this.dropped = true;
      if (this.listeners.size === 0) return;
      this.retry = setTimeout(() => this.connect(), backoffMs(this.attempts++));
    };
  }

  private shutdown() {
    clearTimeout(this.retry);
    this.retry = undefined;
    this.attempts = 0;
    this.dropped = false;
    const ws = this.ws;
    this.ws = null;
    ws?.close();
  }
}
