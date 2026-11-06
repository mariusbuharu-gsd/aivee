import { describe, expect, it } from 'vitest';
import type { AuditEntry } from '../api/client';
import { foldHistory } from './threads';

const edge = { kind: 'device' as const, id: 'edge-sala', name: 'edge-sala' };
const ana = { kind: 'user' as const, id: 'u-ana', name: 'Ana' };
const T0 = Date.parse('2026-11-06T16:39:00Z');

function entry(id: string, kind: string, s: number, over: Partial<AuditEntry> = {}): AuditEntry {
  return {
    id,
    at: new Date(T0 + s * 1000).toISOString(),
    location_id: 'demo',
    actor: edge,
    kind,
    target: { type: 'alert', id: 'e-1', label: 'Masa 1' },
    summary_ro: kind,
    before: null,
    after: null,
    ...over,
  };
}

const rule = entry('r', 'rule.updated', 30, {
  actor: ana,
  target: { type: 'rule', id: 'r-1', label: 'Masă neservită' },
});

describe('foldHistory', () => {
  it('folds one alert into one thread at the place of its newest entry', () => {
    const items = [
      entry('4', 'alert.closed', 120),
      entry('3', 'alert.arrived', 100),
      rule,
      entry('2', 'alert.acknowledged', 60, { actor: ana }),
      entry('1', 'alert.opened', 0, { summary_ro: 'Alertă nouă: Masa 1: nimeni de 1 minut' }),
    ];
    const out = foldHistory(items);
    expect(out.map((i) => i.type)).toEqual(['thread', 'entry']);
    const t = out[0];
    if (t?.type !== 'thread') throw new Error('no thread');
    expect(t).toMatchObject({
      id: 'e-1',
      label: 'Masa 1',
      title: 'Masa 1: nimeni de 1 minut',
      start: items[4]?.at,
      latest: items[0]?.at,
      duration_s: 120,
    });
    expect(t.steps.map((s) => [s.stage, s.offset_s])).toEqual([
      ['opened', 0],
      ['acknowledged', 60],
      ['arrived', 100],
      ['closed', 120],
    ]);
    expect(t.entries.map((e) => e.id)).toEqual(['1', '2', '3', '4']);
  });

  it('keeps separate alerts apart and a re-alert as its own step', () => {
    const other = { type: 'alert', id: 'e-2', label: 'Masa 2' };
    const out = foldHistory([
      entry('b2', 'alert.closed', 300, { target: other }),
      entry('a3', 'alert.realerted', 200),
      entry('b1', 'alert.opened', 150, { target: other }),
      entry('a2', 'alert.acknowledged', 60, { actor: ana }),
      entry('a1', 'alert.opened', 0),
    ]);
    expect(out.map((i) => (i.type === 'thread' ? i.id : i.entry.id))).toEqual(['e-2', 'e-1']);
    const a = out[1];
    if (a?.type !== 'thread') throw new Error('no thread');
    expect(a.steps.map((s) => s.stage)).toEqual(['opened', 'acknowledged', 'realerted']);
    expect(a.duration_s).toBeNull();
  });

  it('leaves a lone alert entry and everything else untouched', () => {
    const lone = entry('2', 'alert.acknowledged', 60, { actor: ana });
    expect(foldHistory([rule, lone])).toEqual([
      { type: 'entry', entry: rule },
      { type: 'entry', entry: lone },
    ]);
  });

  it('starts the thread at the earliest loaded entry when the opening is on an older page', () => {
    const out = foldHistory([entry('3', 'alert.closed', 90), entry('2', 'alert.arrived', 40)]);
    const t = out[0];
    if (t?.type !== 'thread') throw new Error('no thread');
    expect(t.title).toBe('Alertă la Masa 1');
    expect(t.steps.map((s) => s.offset_s)).toEqual([0, 50]);
    expect(t.duration_s).toBeNull();
  });
});
