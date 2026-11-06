import { describe, expect, it, vi } from 'vitest';
import { notificationFromPush } from './payload';
import { PushError, PushService, urlBase64ToBytes, type PushDeps } from './service';

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const SUB_JSON = { endpoint: 'https://push.example/abc', keys: { p256dh: 'P', auth: 'A' } };

function fakeSubscription() {
  return {
    endpoint: SUB_JSON.endpoint,
    toJSON: () => SUB_JSON,
    unsubscribe: vi.fn(async () => true),
  } as unknown as PushSubscription & { unsubscribe: ReturnType<typeof vi.fn> };
}

function setup(
  opts: {
    permission?: NotificationPermission;
    answer?: NotificationPermission;
    existing?: PushSubscription | null;
    responses?: Response[];
    apiBase?: string;
    deps?: Partial<PushDeps>;
  } = {},
) {
  const fetch = vi.fn<typeof globalThis.fetch>();
  for (const r of opts.responses ?? []) fetch.mockResolvedValueOnce(r);
  const created = fakeSubscription();
  let current: PushSubscription | null = opts.existing ?? null;
  const pushManager = {
    getSubscription: vi.fn(async () => current),
    subscribe: vi.fn<(options: PushSubscriptionOptionsInit) => Promise<PushSubscription>>(
      async () => {
        current = created;
        return created;
      },
    ),
  };
  const notification = {
    permission: opts.permission ?? 'default',
    requestPermission: vi.fn(async () => opts.answer ?? 'granted'),
  };
  const service = new PushService({
    apiBase: opts.apiBase ?? 'http://api:8000/',
    fetch,
    serviceWorker: {
      ready: Promise.resolve({ pushManager } as unknown as ServiceWorkerRegistration),
    },
    notification,
    hasPushManager: true,
    secureContext: true,
    ...opts.deps,
  });
  return { service, fetch, pushManager, notification, created };
}

describe('PushService', () => {
  it('is unsupported without a secure context or PushManager', async () => {
    expect(await setup({ deps: { secureContext: false } }).service.state()).toBe('unsupported');
    expect(await setup({ deps: { hasPushManager: false } }).service.state()).toBe('unsupported');
    expect(await setup({ deps: { serviceWorker: undefined } }).service.state()).toBe('unsupported');
  });

  it('is unavailable in mock mode or when the server has no VAPID keys', async () => {
    expect(await setup({ apiBase: '' }).service.state()).toBe('unavailable');
    const { service } = setup({ responses: [json({ detail: {} }, 503)] });
    expect(await service.state()).toBe('unavailable');
  });

  it('reports denied without asking again', async () => {
    const { service, notification } = setup({ permission: 'denied' });
    expect(await service.state()).toBe('denied');
    expect(notification.requestPermission).not.toHaveBeenCalled();
  });

  it('is on when this browser already has a subscription', async () => {
    const { service, fetch } = setup({ existing: fakeSubscription() });
    expect(await service.state()).toBe('on');
    expect(fetch).not.toHaveBeenCalled();
  });

  it('is off when supported, configured and not subscribed', async () => {
    const { service } = setup({ responses: [json({ public_key: 'BPUB' })] });
    expect(await service.state()).toBe('off');
  });

  it('enable: asks permission, subscribes with the VAPID key and registers with the API', async () => {
    const { service, fetch, pushManager } = setup({
      responses: [json({ public_key: 'AQID' }), json({ subscribed: true }, 201)],
    });
    expect(await service.enable()).toBe('on');
    expect(fetch.mock.calls[0]?.[0]).toBe('http://api:8000/api/push/public-key');
    const options = pushManager.subscribe.mock.calls[0]?.[0] ?? {};
    expect(options.userVisibleOnly).toBe(true);
    expect(Array.from(options.applicationServerKey as Uint8Array)).toEqual([1, 2, 3]);
    const [url, init] = fetch.mock.calls[1] ?? [];
    expect(url).toBe('http://api:8000/api/push/subscribe');
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual(SUB_JSON);
  });

  it('enable: a refused prompt ends in denied and nothing is subscribed', async () => {
    const { service, pushManager, fetch } = setup({ answer: 'denied' });
    expect(await service.enable()).toBe('denied');
    expect(pushManager.subscribe).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('enable: surfaces the Romanian server message on failure', async () => {
    const { service } = setup({
      responses: [
        json({ public_key: 'AQID' }),
        json({ detail: { code: 'invalid', message_ro: 'Abonament invalid.' } }, 422),
      ],
    });
    await expect(service.enable()).rejects.toThrow('Abonament invalid.');
  });

  it('disable: deletes on the server, then unsubscribes the browser', async () => {
    const existing = fakeSubscription();
    const { service, fetch } = setup({
      existing,
      responses: [new Response(null, { status: 204 })],
    });
    expect(await service.disable()).toBe('off');
    const [url, init] = fetch.mock.calls[0] ?? [];
    expect(url).toBe('http://api:8000/api/push/subscribe');
    expect(init?.method).toBe('DELETE');
    expect(JSON.parse(String(init?.body))).toEqual({ endpoint: SUB_JSON.endpoint });
    expect(existing.unsubscribe).toHaveBeenCalled();
  });

  it('network errors become a PushError in Romanian', async () => {
    const { service, fetch } = setup();
    fetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const err = await service.state().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(PushError);
    expect((err as Error).message).toMatch(/Serverul nu răspunde/);
  });

  it('sendTest returns the report', async () => {
    const { service } = setup({ responses: [json({ sent: 2, removed: 1, failed: 0 })] });
    expect(await service.sendTest()).toEqual({ sent: 2, removed: 1, failed: 0 });
  });
});

describe('urlBase64ToBytes', () => {
  it('decodes unpadded base64url', () => {
    expect(Array.from(urlBase64ToBytes('-_8'))).toEqual([251, 255]);
  });
});

describe('notificationFromPush', () => {
  it('uses the payload and opens the given path', () => {
    const n = notificationFromPush({
      title: 'Alertă AiVee · Masa 1',
      body: 'Masa 1 așteaptă de 1 min',
      url: '/alerte',
      tag: 'e1',
    });
    expect(n.title).toBe('Alertă AiVee · Masa 1');
    expect(n.options).toMatchObject({ body: 'Masa 1 așteaptă de 1 min', tag: 'e1', lang: 'ro' });
    expect(n.options.data).toEqual({ url: '/alerte' });
  });

  it('falls back to /alerte for missing or foreign urls', () => {
    expect(notificationFromPush({}).options.data).toEqual({ url: '/alerte' });
    expect(notificationFromPush({ url: 'https://evil.example' }).options.data).toEqual({
      url: '/alerte',
    });
  });

  it('rings again for a re-alert but replaces the alarm quietly on ack', () => {
    const realert = notificationFromPush({ title: 'AiVee · Nu a ajuns nimeni', tag: 'e1' });
    expect(realert.options).toMatchObject({ tag: 'e1', renotify: true });
    const ack = notificationFromPush({ title: 'AiVee · Preluată', tag: 'e1' });
    expect(ack.options).toMatchObject({ tag: 'e1', renotify: false });
  });

  it('honours an explicit kind over the title', () => {
    expect(notificationFromPush({ title: 'x', kind: 'realert' }).options.renotify).toBe(true);
  });
});
