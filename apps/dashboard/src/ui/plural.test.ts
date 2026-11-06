import { describe, expect, it } from 'vitest';
import { plural } from './plural';

describe('plural', () => {
  it('uses the singular for one and "de" from twenty', () => {
    expect(plural(0, 'zonă', 'zone')).toBe('0 zone');
    expect(plural(1, 'zonă', 'zone')).toBe('1 zonă');
    expect(plural(2, 'zonă', 'zone')).toBe('2 zone');
    expect(plural(19, 'persoană', 'persoane')).toBe('19 persoane');
    expect(plural(20, 'persoană', 'persoane')).toBe('20 de persoane');
    expect(plural(101, 'zonă', 'zone')).toBe('101 zone');
    expect(plural(100, 'zonă', 'zone')).toBe('100 de zone');
  });
});
