import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Rule } from '../contracts';
import { ApiError } from './client';
import { HttpApi } from './http';

const rule: Rule = {
  id: 'r-1',
  camera_id: 'cam-01',
  name: 'Masă neservită',
  prompt_ro: 'Anunță-mă dacă la o masă nu vine nimeni de 1 minut',
  zone_tag: 'table',
  all_of: [{ kind: 'absent', role: 'staff', min_duration_s: 60 }],
  action: { type: 'telegram' },
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

function mockFetch(...responses: Response[]) {
  const fn = vi.fn<typeof fetch>();
  for (const r of responses) fn.mockResolvedValueOnce(r);
  vi.stubGlobal('fetch', fn);
  return fn;
}

const body = (fn: ReturnType<typeof mockFetch>, call = 0) =>
  JSON.parse(String(fn.mock.calls[call]?.[1]?.body)) as unknown;

afterEach(() => vi.unstubAllGlobals());

describe('HttpApi', () => {
  const api = new HttpApi('http://api:8000/');

  it('drafts a rule from text without saving it', async () => {
    const fetch = mockFetch(json({ rule, explanation_ro: 'Vă anunț…', saved: false }));
    const draft = await api.draftRuleFromText('Anunță-mă', 'cam-01');
    expect(fetch.mock.calls[0]?.[0]).toBe('http://api:8000/api/rules/from-text');
    expect(body(fetch)).toEqual({ text: 'Anunță-mă', camera_id: 'cam-01', save: false });
    expect(draft).toEqual({ rule, explanation_ro: 'Vă anunț…' });
  });

  it('saves a confirmed rule through POST /api/rules', async () => {
    const fetch = mockFetch(json(rule, 201));
    expect(await api.createRule(rule)).toEqual(rule);
    expect(fetch.mock.calls[0]?.[0]).toBe('http://api:8000/api/rules');
    expect(fetch.mock.calls[0]?.[1]?.method).toBe('POST');
    expect(body(fetch)).toEqual(rule);
  });

  it('creates a camera with the chosen id', async () => {
    const out = {
      id: 'cam-01',
      name: 'Sala',
      source: 's',
      zones: [],
      device: 'edge-01',
      online: false,
    };
    const fetch = mockFetch(json(out, 201));
    const cam = await api.createCamera({
      id: 'cam-01',
      name: 'Sala',
      source: 's',
      device: 'edge-01',
    });
    expect(body(fetch)).toMatchObject({ id: 'cam-01', name: 'Sala', source: 's' });
    expect(cam.online).toBe(false);
  });

  it('surfaces message_ro from domain errors', async () => {
    mockFetch(json({ detail: { code: 'clarify', message_ro: 'Desenați o masă.' } }, 422));
    const err = await api.draftRuleFromText('x y z', 'cam-01').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ message: 'Desenați o masă.', code: 'clarify', status: 422 });
  });

  it('maps validation and network errors to Romanian messages', async () => {
    mockFetch(json({ detail: [{ loc: ['body', 'text'], msg: 'too short' }] }, 422));
    await expect(api.listRules()).rejects.toMatchObject({
      message: 'Date invalide: verificați text.',
      code: 'invalid',
    });
    mockFetch(
      json(
        {
          detail: {
            code: 'camera_site',
            message_ro: 'Camera poate fi adăugată doar la Terasa demo.',
          },
        },
        422,
      ),
    );
    await expect(api.listRules()).rejects.toMatchObject({
      message: 'Camera poate fi adăugată doar la Terasa demo.',
      code: 'camera_site',
      status: 422,
    });
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(api.listRules()).rejects.toMatchObject({ code: 'network' });
  });

  it('resolves snapshot urls against the API base', async () => {
    const ev = {
      event_id: 'e-1',
      rule_id: 'r-1',
      camera_id: 'cam-01',
      zone_id: 'z-1',
      state: 'opened',
      at: '2026-11-06T10:00:00Z',
      summary_ro: 'Masa 1',
      snapshot: true,
    };
    mockFetch(
      json([
        {
          ...ev,
          snapshot_url: '/api/snapshots/e-1',
          before_snapshot_url: '/api/snapshots/e-1-before',
        },
        { ...ev, event_id: 'e-2', snapshot: false, snapshot_url: null },
      ]),
    );
    const [a, b] = await api.listAlerts();
    expect(a?.snapshot_url).toBe('http://api:8000/api/snapshots/e-1');
    expect(a?.before_snapshot_url).toBe('http://api:8000/api/snapshots/e-1-before');
    expect(b?.snapshot_url).toBeNull();
    expect(b?.before_snapshot_url).toBeNull();
  });
});

describe('HttpApi videos', () => {
  const upload = {
    id: '3f9a2c1d',
    location_id: 'centru',
    camera_id: 'video-3f9a2c1d',
    source_camera_id: 'cam-01',
    filename: 'sala-1.mp4',
    size_bytes: 1024,
    rotate: 90,
    status: 'queued',
    progress: 0,
    duration_s: null,
    events: 0,
    error_ro: null,
    created_at: '2026-11-06T10:00:00Z',
    started_at: null,
    finished_at: null,
    created_by: null,
  };

  it('uploads the clip as multipart with the location, rotation and source camera', async () => {
    const api = new HttpApi('http://api:8000');
    api.setLocation('centru');
    const fetch = mockFetch(json(upload, 201));
    const file = new File(['x'], 'sala-1.mp4', { type: 'video/mp4' });
    expect(await api.uploadVideo({ file, rotate: 90, copy_from_camera_id: 'cam-01' })).toEqual(
      upload,
    );
    const [url, init] = fetch.mock.calls[0] ?? [];
    expect(String(url)).toMatch(/^http:\/\/api:8000\/api\/videos/);
    expect(init?.method).toBe('POST');
    expect(init?.credentials).toBe('include');
    const form = init?.body as FormData;
    expect(form.get('file')).toBeInstanceOf(File);
    expect(form.get('location_id')).toBe('centru');
    expect(form.get('rotate')).toBe('90');
    expect(form.get('copy_from_camera_id')).toBe('cam-01');
    // The browser sets the multipart boundary itself.
    expect(new Headers(init?.headers).get('Content-Type')).toBeNull();
  });

  it('leaves out the optional fields and shows the API message on 422', async () => {
    const api = new HttpApi('http://api:8000');
    api.setLocation('centru');
    const fetch = mockFetch(
      json({ detail: { code: 'too_long', message_ro: 'Clipul are mai mult de 2 minute.' } }, 422),
    );
    const file = new File(['x'], 'lung.mp4', { type: 'video/mp4' });
    await expect(api.uploadVideo({ file })).rejects.toMatchObject({
      message: 'Clipul are mai mult de 2 minute.',
      status: 422,
    });
    const form = fetch.mock.calls[0]?.[1]?.body as FormData;
    expect(form.has('rotate')).toBe(false);
    expect(form.has('copy_from_camera_id')).toBe(false);
  });

  it('lists, reads and fetches the alerts of an upload with absolute snapshot urls', async () => {
    const api = new HttpApi('http://api:8000');
    api.setLocation('centru');
    const alert = {
      event_id: 'e-1',
      zone_id: 'z-1',
      zone_name: 'Masa 2',
      summary_ro: 'Masa 2: neservită de 1 min',
      state: 'closed',
      at_s: 12,
      arrived_at_s: 40,
      closed_at_s: 41,
      wait_s: 29,
      closed_reason: null,
      snapshot_url: '/api/snapshots/e-1',
    };
    const fetch = mockFetch(
      json([upload]),
      json(upload),
      json([alert, { ...alert, event_id: 'e-2', snapshot_url: null }]),
    );
    expect(await api.listVideos()).toEqual([upload]);
    expect(await api.getVideo('3f9a2c1d')).toEqual(upload);
    const [a, b] = await api.videoEvents('3f9a2c1d');
    expect(fetch.mock.calls.map(([u]) => String(u))).toEqual([
      'http://api:8000/api/videos?location_id=centru',
      'http://api:8000/api/videos/3f9a2c1d?location_id=centru',
      'http://api:8000/api/videos/3f9a2c1d/events?location_id=centru',
    ]);
    expect(a?.snapshot_url).toBe('http://api:8000/api/snapshots/e-1');
    expect(b?.snapshot_url).toBeNull();
  });
});

describe('HttpApi accounts (auth-roles-audit spec)', () => {
  it('sends the session cookie and scopes resources to the current location', async () => {
    const api = new HttpApi('http://api:8000');
    const fetch = mockFetch(json([]), json([]), json({ user: {} }));
    api.setLocation('terasa');
    await api.listCameras();
    await api.listAlertCases({ location_id: 'centru', state: 'open' });
    await api.me();
    expect(fetch.mock.calls[0]?.[0]).toBe('http://api:8000/api/cameras?location_id=terasa');
    expect(fetch.mock.calls[0]?.[1]?.credentials).toBe('include');
    expect(fetch.mock.calls[1]?.[0]).toBe(
      'http://api:8000/api/alerts?location_id=centru&state=open',
    );
    expect(fetch.mock.calls[2]?.[0]).toBe('http://api:8000/api/auth/me');
  });

  it('announces a 401 so the app returns to /intra, except for the auth calls', async () => {
    const api = new HttpApi('http://api:8000');
    const seen = vi.fn();
    window.addEventListener('aivee:unauthorized', seen);
    const err = { detail: { code: 'unauthenticated', message_ro: 'Intră în cont.' } };
    mockFetch(json(err, 401), json(err, 401));
    await expect(api.listRules()).rejects.toMatchObject({ status: 401 });
    await expect(api.me()).rejects.toMatchObject({ status: 401 });
    expect(seen).toHaveBeenCalledTimes(1);
    window.removeEventListener('aivee:unauthorized', seen);
  });

  it('treats a socket closed with 1008 (no session) like a 401 and stops reconnecting', () => {
    const sockets: { onclose: ((e: CloseEvent) => void) | null; close: () => void }[] = [];
    class FakeSocket {
      onclose: ((e: CloseEvent) => void) | null = null;
      onmessage: unknown = null;
      constructor() {
        sockets.push(this);
      }
      close() {}
    }
    vi.stubGlobal('WebSocket', FakeSocket);
    vi.useFakeTimers();
    const seen = vi.fn();
    window.addEventListener('aivee:unauthorized', seen);
    const off = new HttpApi('http://api:8000').subscribeAlerts(() => undefined);
    sockets[0]?.onclose?.({ code: 1008 } as CloseEvent);
    vi.advanceTimersByTime(5000);
    expect(seen).toHaveBeenCalledTimes(1);
    expect(sockets).toHaveLength(1);
    off();
    window.removeEventListener('aivee:unauthorized', seen);
    vi.useRealTimers();
  });

  it('acknowledges an alert with "Merg eu"', async () => {
    const api = new HttpApi('http://api:8000');
    const fetch = mockFetch(json({ event_id: 'e-1', acknowledged_by: 'Ana' }));
    await api.ackAlert('e-1');
    expect(fetch.mock.calls[0]?.[0]).toBe('http://api:8000/api/alerts/e-1/ack');
    expect(fetch.mock.calls[0]?.[1]?.method).toBe('POST');
  });
});

describe('HttpApi counts', () => {
  it('asks for 7 days of rule stats at the current location', async () => {
    const api = new HttpApi('http://api:8000');
    const stats = { days: ['2026-11-06'], rules: [{ rule_id: 'r-1', total: 2, per_day: [2] }] };
    const fetch = mockFetch(json(stats));
    api.setLocation('terasa');
    expect(await api.getRuleStats()).toEqual(stats);
    expect(fetch.mock.calls[0]?.[0]).toBe(
      'http://api:8000/api/rules/stats?days=7&location_id=terasa',
    );
  });
});
