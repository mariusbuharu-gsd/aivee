import { describe, expect, it } from 'vitest';
import { describeChanges } from './diff';

describe('describeChanges', () => {
  it('says what changed in words', () => {
    expect(
      describeChanges(
        { id: 'r', name: 'Masă', enabled: true, cooldown_s: 60, zones: [{ name: 'Masa 1' }] },
        {
          id: 'r',
          name: 'Masă',
          enabled: false,
          cooldown_s: 120,
          zones: [{ name: 'Masa 1' }, { name: 'Masa 2' }],
        },
      ),
    ).toEqual([
      { label: 'Activă', from: 'da', to: 'nu' },
      { label: 'Pauză între alerte', from: '1 min', to: '2 min' },
      { label: 'Zone', from: 'Masa 1', to: 'Masa 1, Masa 2' },
    ]);
  });

  it('handles a created or deleted object and roles', () => {
    expect(describeChanges({ role: 'staff' }, { role: 'manager' })).toEqual([
      { label: 'Rol', from: 'Personal', to: 'Manager' },
    ]);
    expect(describeChanges(null, { name: 'Bar' })).toEqual([
      { label: 'Nume', from: '—', to: 'Bar' },
    ]);
  });

  it('says rule condition times in words, never as field names', () => {
    expect(describeChanges({ absent_staff_s: 300 }, { absent_staff_s: 120 })).toEqual([
      { label: 'Nimeni de la personal', from: '5 min', to: '2 min' },
    ]);
    const rule = (s: number) => ({
      all_of: [
        { kind: 'present', role: 'guest', min_duration_s: 60 },
        { kind: 'absent', role: 'staff', min_duration_s: s },
      ],
    });
    expect(describeChanges(rule(300), rule(90))).toEqual([
      { label: 'Nimeni de la personal', from: '5 min', to: '1 min 30 s' },
    ]);
  });

  it('says a reshaped condition list as a sentence and hides unnamed fields', () => {
    expect(
      describeChanges(
        { all_of: [{ kind: 'pose', role: 'guest', pose: 'raised_hand' }], internal_x: 1 },
        { all_of: [{ kind: 'absent', role: 'staff', min_duration_s: 60 }], internal_x: 2 },
      ),
    ).toEqual([
      {
        label: 'Condiții',
        from: 'un client ridică mâna',
        to: 'nu a venit cineva de la personal de 1 minut',
      },
    ]);
  });
});
