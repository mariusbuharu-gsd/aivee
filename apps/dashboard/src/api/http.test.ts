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
      message: 'Datele trimise nu sunt valide.',
      code: 'invalid',
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
        { ...ev, snapshot_url: '/api/snapshots/e-1' },
        { ...ev, event_id: 'e-2', snapshot: false, snapshot_url: null },
      ]),
    );
    const [a, b] = await api.listAlerts();
    expect(a?.snapshot_url).toBe('http://api:8000/api/snapshots/e-1');
    expect(b?.snapshot_url).toBeNull();
  });
});
