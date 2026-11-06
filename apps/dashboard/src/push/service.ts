// Web Push subscription for this device: browser support, permission, subscribe/unsubscribe
// against the API (`/api/push/*`). Browser objects are injected so the logic is tested with mocks.

/** What the toggle shows. */
export type PushState =
  | 'unsupported' // no service worker / PushManager / Notification, or not a secure context
  | 'unavailable' // no API (demo mock) or the server has no VAPID keys
  | 'denied' // the user blocked notifications for this site
  | 'off'
  | 'on';

export interface PushDeps {
  /** API base URL; empty in mock mode. */
  apiBase: string;
  fetch: typeof fetch;
  serviceWorker?: Pick<ServiceWorkerContainer, 'ready'>;
  notification?: {
    readonly permission: NotificationPermission;
    requestPermission(): Promise<NotificationPermission>;
  };
  hasPushManager: boolean;
  secureContext: boolean;
}

export interface TestReport {
  sent: number;
  removed: number;
  failed: number;
}

export class PushError extends Error {}

const NETWORK = 'Serverul nu răspunde. Verifică conexiunea.';
const NO_WORKER = 'Aplicația nu s-a instalat încă pe acest dispozitiv. Reîncarcă pagina.';
const READY_TIMEOUT_MS = 5_000;

/** VAPID public key (base64url) → the bytes `pushManager.subscribe` wants. */
export function urlBase64ToBytes(base64: string): Uint8Array<ArrayBuffer> {
  const padded = (base64 + '='.repeat((4 - (base64.length % 4)) % 4))
    .replace(/-/g, '+')
    .replace(/_/g, '/');
  const raw = atob(padded);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export class PushService {
  private readonly base: string;

  constructor(private readonly deps: PushDeps) {
    this.base = deps.apiBase.replace(/\/$/, '');
  }

  get supported(): boolean {
    const d = this.deps;
    return d.secureContext && !!d.serviceWorker && !!d.notification && d.hasPushManager;
  }

  /** Current state, without prompting the user. */
  async state(): Promise<PushState> {
    if (!this.supported) return 'unsupported';
    if (!this.base) return 'unavailable';
    if (this.deps.notification?.permission === 'denied') return 'denied';
    const sub = await this.currentSubscription();
    if (sub) return 'on';
    return (await this.publicKey()) ? 'off' : 'unavailable';
  }

  /** Ask for permission, subscribe this device and register it with the API. */
  async enable(): Promise<PushState> {
    if (!this.supported) return 'unsupported';
    if (!this.base) return 'unavailable';
    const permission = await this.deps.notification?.requestPermission();
    if (permission === 'denied') return 'denied';
    if (permission !== 'granted') return 'off'; // dismissed the prompt
    const key = await this.publicKey();
    if (!key) return 'unavailable';
    const reg = await this.registration();
    const sub =
      (await reg.pushManager.getSubscription()) ??
      (await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToBytes(key),
      }));
    await this.call('/api/push/subscribe', 'POST', sub.toJSON());
    return 'on';
  }

  /** Forget this device on the server and in the browser. */
  async disable(): Promise<PushState> {
    const sub = await this.currentSubscription();
    if (sub) {
      await this.call('/api/push/subscribe', 'DELETE', { endpoint: sub.endpoint });
      await sub.unsubscribe();
    }
    return 'off';
  }

  async sendTest(): Promise<TestReport> {
    const res = await this.call('/api/push/test', 'POST');
    return (await res.json()) as TestReport;
  }

  private async currentSubscription(): Promise<PushSubscription | null> {
    if (!this.supported) return null;
    return (await this.registration()).pushManager.getSubscription();
  }

  /** `serviceWorker.ready` never settles without a registered worker, so give up after a while. */
  private async registration(): Promise<ServiceWorkerRegistration> {
    const ready = this.deps.serviceWorker?.ready;
    if (!ready) throw new PushError(NO_WORKER);
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new PushError(NO_WORKER)), READY_TIMEOUT_MS);
    });
    try {
      return await Promise.race([ready, timeout]);
    } finally {
      clearTimeout(timer);
    }
  }

  private async publicKey(): Promise<string | null> {
    let res: Response;
    try {
      res = await this.deps.fetch(`${this.base}/api/push/public-key`);
    } catch {
      throw new PushError(NETWORK);
    }
    if (res.status === 503 || res.status === 404) return null; // no VAPID keys / old API
    if (!res.ok) throw new PushError(`Eroare de server (${res.status}).`);
    const body = (await res.json()) as { public_key?: unknown };
    return typeof body.public_key === 'string' && body.public_key ? body.public_key : null;
  }

  private async call(path: string, method: string, body?: unknown): Promise<Response> {
    let res: Response;
    try {
      res = await this.deps.fetch(`${this.base}${path}`, {
        method,
        headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new PushError(NETWORK);
    }
    if (!res.ok) {
      let message = `Eroare de server (${res.status}).`;
      try {
        const detail = ((await res.json()) as { detail?: { message_ro?: unknown } }).detail;
        if (typeof detail?.message_ro === 'string') message = detail.message_ro;
      } catch {
        /* not JSON */
      }
      throw new PushError(message);
    }
    return res;
  }
}

/** The service for this browser tab. */
export function browserPushService(apiBase = import.meta.env.VITE_API_URL ?? ''): PushService {
  const nav = typeof navigator === 'undefined' ? undefined : navigator;
  return new PushService({
    apiBase,
    fetch: (...args) => fetch(...args),
    serviceWorker: nav && 'serviceWorker' in nav ? nav.serviceWorker : undefined,
    notification: typeof Notification === 'undefined' ? undefined : Notification,
    hasPushManager: typeof window !== 'undefined' && 'PushManager' in window,
    secureContext: typeof window !== 'undefined' && window.isSecureContext,
  });
}
