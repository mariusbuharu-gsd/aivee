import { describe, expect, it } from 'vitest';
import type { AlertView } from '../api/client';
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

  it('remembers why the system closed an alert', () => {
    const [item] = foldAlerts([
      ev('a', 'opened', '2026-11-06T10:00:00Z'),
      {
        ...ev('b', 'closed', '2026-11-06T10:02:00Z'),
        closed_by: 'system',
        closed_reason: 'device_offline',
      },
    ] as AlertView[]);
    expect(item?.closed_reason).toBe('device_offline');
  });

  it('keeps the AI verification and the before snapshot, and takes later updates', () => {
    const opened = {
      ...ev('a', 'opened', '2026-11-06T10:00:00Z'),
      snapshot_url: '/api/snapshots/a',
      before_snapshot_url: '/api/snapshots/a-before',
      verification: { status: 'pending' },
    } as AlertView;
    const [first] = foldAlerts([opened]);
    expect(first?.verification?.status).toBe('pending');
    expect(first?.before_snapshot_url).toBe('/api/snapshots/a-before');

    const [item] = foldAlerts([
      opened,
      {
        ...opened,
        verification: { status: 'confirmed', summary_ro: 'Masa 1: a dispărut paharul' },
      },
    ]);
    expect(item?.verification).toEqual({
      status: 'confirmed',
      summary_ro: 'Masa 1: a dispărut paharul',
    });
    expect(item?.snapshot_url).toBe('/api/snapshots/a');
  });

  it('leaves plain alerts without verification', () => {
    const [item] = foldAlerts([ev('a', 'opened', '2026-11-06T10:00:00Z')]);
    expect(item?.verification).toBeUndefined();
    expect(item?.before_snapshot_url).toBeUndefined();
  });
});
