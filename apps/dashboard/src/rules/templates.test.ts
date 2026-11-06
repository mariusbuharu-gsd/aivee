import { describe, expect, it } from 'vitest';
import { mockRuleFromText } from '../api/mock';
import { ruleTemplates } from './templates';

describe('ruleTemplates', () => {
  it('restaurant and terrace get the table examples', () => {
    for (const type of ['restaurant', 'terrace']) {
      expect(ruleTemplates(type)).toEqual([
        'Anunță-mă dacă la o masă nu vine nimeni de 2 minute',
        'Anunță-mă dacă un client ridică mâna',
        'Anunță-mă dacă o masă rămâne nedebarasată 3 minute după ce pleacă clienții',
        'Anunță-mă dacă dispare un pahar de pe masă',
      ]);
    }
  });

  it('a shop and an event start with a queue at the entrance', () => {
    for (const type of ['shop', 'event']) {
      const list = ruleTemplates(type);
      expect(list[0]).toMatch(/la intrare sunt cel puțin \d+ persoane/);
      expect(list).not.toEqual(ruleTemplates('restaurant'));
    }
  });

  it('every API location type has 3–4 examples; unknown types get the general set', () => {
    for (const type of ['restaurant', 'terrace', 'event', 'shop', 'other']) {
      const list = ruleTemplates(type);
      expect(list.length).toBeGreaterThanOrEqual(3);
      expect(list.length).toBeLessThanOrEqual(4);
      expect(new Set(list).size).toBe(list.length);
    }
    expect(ruleTemplates('pizzerie')).toEqual(ruleTemplates('other'));
    expect(ruleTemplates(undefined)).toEqual(ruleTemplates('other'));
  });

  it('the examples draft the intended rule in the mock', () => {
    const [unservedText = '', handText = ''] = ruleTemplates('restaurant');
    const [queueText = ''] = ruleTemplates('shop');
    const queue = mockRuleFromText(queueText, 'cam-sala');
    expect(queue.zone_tag).toBe('entrance');
    expect(queue.all_of[0]).toMatchObject({ kind: 'count', min_count: 4 });
    expect(mockRuleFromText(handText, 'c').all_of[0].kind).toBe('pose');
    const unserved = mockRuleFromText(unservedText, 'c');
    expect(unserved.all_of).toContainEqual({ kind: 'absent', role: 'staff', min_duration_s: 120 });
  });
});
