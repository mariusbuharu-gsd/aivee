import { describe, expect, it } from 'vitest';
import type { AlertItem } from '../alerts/fold';
import { elapsed, openAlerts, ringFill, roomStatus, tick } from './room';

const alert = (key: string, opened_at: string, closed_at: string | null = null) =>
  ({ key, opened_at, closed_at }) as AlertItem;

describe('room', () => {
  it('lists open alerts, the longest waiting first', () => {
    const items = [
      alert('a', '2026-11-06T17:02:00Z'),
      alert('b', '2026-11-06T17:00:00Z', '2026-11-06T17:01:00Z'),
      alert('c', '2026-11-06T16:58:00Z'),
    ];
    expect(openAlerts(items).map((a) => a.key)).toEqual(['c', 'a']);
  });

  it('ticks minutes and seconds and fills the ring up to five minutes', () => {
    const now = Date.parse('2026-11-06T17:02:05Z');
    expect(tick(elapsed(alert('a', '2026-11-06T17:00:00Z'), now))).toBe('2:05');
    expect(tick(-3)).toBe('0:00');
    expect(ringFill(150)).toBe(0.5);
    expect(ringFill(900)).toBe(1);
  });

  it('says the state in one line and adds only the facts that matter', () => {
    const cams = [{ online: true }, { online: false }];
    expect(roomStatus(0, cams, 2)).toEqual({
      title: 'Totul e în regulă.',
      facts: ['2 alerte azi', '1 cameră offline'],
    });
    expect(roomStatus(1, [{ online: true }], 1)).toEqual({
      title: 'O masă așteaptă.',
      facts: ['1 alertă azi'],
    });
    expect(roomStatus(3, [], null)).toEqual({ title: '3 mese așteaptă.', facts: [] });
  });
});
