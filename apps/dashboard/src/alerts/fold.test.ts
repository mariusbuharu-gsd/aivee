import { describe, expect, it } from 'vitest';
import type { AlertEvent } from '../contracts';
import { foldAlerts } from './fold';

const ev = (id: string, state: AlertEvent['state'], at: string, zone = 'z1'): AlertEvent => ({
  event_id: id,
  rule_id: 'r1',
  camera_id: 'c1',
  zone_id: zone,
  state,
  at,
  summary_ro: `ev ${id}`,
});

describe('foldAlerts', () => {
  it('pairs opened and closed events, newest first', () => {
    const items = foldAlerts([
      ev('a', 'opened', '2026-11-06T10:00:00Z'),
      ev('b', 'closed', '2026-11-06T10:02:00Z'),
      ev('c', 'opened', '2026-11-06T10:05:00Z', 'z2'),
    ]);
    expect(items.map((i) => [i.key, i.closed_at])).toEqual([
      ['c', null],
      ['a', '2026-11-06T10:02:00Z'],
    ]);
  });

  it('ignores duplicate event ids and stray closes', () => {
    const items = foldAlerts([
      ev('x', 'closed', '2026-11-06T09:00:00Z'),
      ev('a', 'opened', '2026-11-06T10:00:00Z'),
      ev('a', 'opened', '2026-11-06T10:00:00Z'),
    ]);
    expect(items).toHaveLength(1);
    expect(items[0]?.closed_at).toBeNull();
  });
});
