import { describe, expect, it } from 'vitest';
import type { Rule } from '../contracts';
import { barTones, headline, serviceTarget, shortDuration } from './insight';

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
