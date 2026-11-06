import { describe, expect, it } from 'vitest';
import type { Rule } from '../contracts';
import {
  barTones,
  heatHours,
  heatLabel,
  heatLevel,
  headline,
  pickTarget,
  serviceTarget,
  shortDuration,
  targetSeconds,
} from './insight';

const rule = (over: Partial<Rule>): Rule => ({
  id: 'r',
  camera_id: 'cam',
  name: 'Regulă',
  prompt_ro: '',
  zone_tag: 'table',
  all_of: [{ kind: 'pose', role: 'guest', pose: 'raised_hand' }],
  action: { type: 'push' },
  enabled: true,
  ...over,
});

describe('headline', () => {
  it('says whether guests waited less or more than before', () => {
    expect(headline(7, 104, 122)).toEqual({
      value: '1 min 44 s',
      rest: ' în ultimele 7 zile, cu 18 s mai puțin decât în cele 7 zile dinainte.',
      tone: 'better',
    });
    expect(headline(1, 70, 40).rest).toBe(' azi, cu 30 s mai mult decât ieri.');
    expect(headline(1, 70, 40).tone).toBe('worse');
    expect(headline(30, 60, 60.4).tone).toBe('same');
  });

  it('has no comparison without a previous period and no value without data', () => {
    expect(headline(7, 50, null)).toEqual({
      value: '50 s',
      rest: ' în ultimele 7 zile.',
      tone: 'none',
    });
    expect(headline(1, null, 40).value).toBeNull();
  });
});

describe('serviceTarget', () => {
  const absent = (s: number): Rule['all_of'] => [
    { kind: 'present' as const, role: 'guest' as const, min_duration_s: 30 },
    { kind: 'absent' as const, role: 'staff' as const, min_duration_s: s },
  ];

  it("takes the unserved-table rule's staff-absence time", () => {
    expect(
      serviceTarget([
        rule({ id: 'a', name: 'Bar gol', all_of: absent(30) }),
        rule({ id: 'b', name: 'Masă neservită', all_of: absent(90) }),
      ]),
    ).toBe(90);
  });

  it('falls back to the strictest enabled absence rule, else none', () => {
    expect(
      serviceTarget([
        rule({ id: 'a', all_of: absent(120) }),
        rule({ id: 'b', all_of: absent(60) }),
        rule({ id: 'c', all_of: absent(10), enabled: false }),
      ]),
    ).toBe(60);
    expect(serviceTarget([rule({})])).toBeNull();
    expect(serviceTarget([])).toBeNull();
  });
});

describe('barTones', () => {
  it('marks the slowest day, then over and under the target', () => {
    expect(barTones([80, null, 120, 50, 120], 60)).toEqual([
      'over',
      'empty',
      'slowest',
      'under',
      'over',
    ]);
  });

  it('draws every measured day full without a target', () => {
    expect(barTones([10, 20], null)).toEqual(['over', 'slowest']);
    expect(barTones([null], null)).toEqual(['empty']);
  });
});

it('shortDuration fits above a bar', () => {
  expect(shortDuration(117)).toBe('1:57');
  expect(shortDuration(45)).toBe('45 s');
  expect(shortDuration(600)).toBe('10:00');
});

describe('pickTarget', () => {
  it("prefers the location's own target over the rule's time", () => {
    expect(pickTarget(75, 90)).toEqual({ seconds: 75, source: 'location' });
    expect(pickTarget(null, 90)).toEqual({ seconds: 90, source: 'rule' });
    expect(pickTarget(undefined, null)).toBeNull();
  });
});

describe('targetSeconds', () => {
  it('reads minutes and seconds', () => {
    expect(targetSeconds('1', '30')).toBe(90);
    expect(targetSeconds('', '45')).toBe(45);
    expect(targetSeconds('2', '')).toBe(120);
  });

  it('refuses nothing, negatives, fractions and more than an hour', () => {
    expect(targetSeconds('', '')).toBeNull();
    expect(targetSeconds('0', '0')).toBeNull();
    expect(targetSeconds('-1', '0')).toBeNull();
    expect(targetSeconds('1.5', '0')).toBeNull();
    expect(targetSeconds('0', '75')).toBeNull();
    expect(targetSeconds('60', '1')).toBeNull();
    expect(targetSeconds('60', '0')).toBe(3600);
  });
});

type Mark = [day: number, hour: number, alerts: number, wait: number | null];
const grid = (marks: Mark[]) => {
  const cells = Array.from({ length: 7 }, () =>
    Array.from({ length: 24 }, () => ({ alerts: 0, wait_median_s: null as number | null })),
  );
  for (const [d, h, alerts, wait] of marks) (cells[d] ?? [])[h] = { alerts, wait_median_s: wait };
  return cells;
};

describe('heatmap helpers', () => {
  it('shows the hours between the first and the last with data', () => {
    const marks: Mark[] = [
      [1, 12, 1, 60],
      [5, 21, 3, 90],
    ];
    expect(heatHours(grid(marks))).toEqual([12, 13, 14, 15, 16, 17, 18, 19, 20, 21]);
  });

  it('falls back to 10–23 when no hour has data', () => {
    expect(heatHours(grid([]))).toEqual([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]);
  });

  it('labels a cell with the weekday, the hour, the count and the usual wait', () => {
    expect(heatLabel(1, 20, { alerts: 4, wait_median_s: 110 })).toBe(
      'marți 20:00 · 4 alerte · de obicei 1 min 50 s',
    );
    expect(heatLabel(6, 9, { alerts: 1, wait_median_s: 40 })).toBe(
      'duminică 09:00 · 1 alertă · de obicei 40 s',
    );
    expect(heatLabel(0, 15, { alerts: 0, wait_median_s: null })).toBe('luni 15:00 · nicio alertă');
  });

  it('grades the count from 0 (none) to 4 (the busiest cell)', () => {
    expect([0, 1, 5, 10, 20].map((n) => heatLevel(n, 20))).toEqual([0, 1, 1, 2, 4]);
    expect(heatLevel(3, 0)).toBe(0);
  });
});
