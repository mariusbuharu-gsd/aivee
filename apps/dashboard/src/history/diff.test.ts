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
      { label: 'Pauză între alerte', from: '1 min 0 s', to: '2 min 0 s' },
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
});
