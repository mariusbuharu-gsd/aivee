import { describe, expect, it } from 'vitest';
import { mockRuleFromText } from '../api/mock';
import { ruleTemplates } from './templates';

describe('ruleTemplates', () => {
  it('restaurant and terrace get the table examples', () => {
    for (const type of ['restaurant', 'terrace']) {
      expect(ruleTemplates(type)).toEqual([
        'Anunță-mă dacă apare un urs',
        'Anunță-mă dacă e foc',
        'Anunță-mă dacă la o masă nu vine nimeni de 2 minute',
        'Anunță-mă dacă un client ridică mâna',
        'Anunță-mă dacă dispare un pahar de pe masă',
      ]);
    }
  });

  it('every type starts with the two open examples', () => {
    for (const type of ['restaurant', 'terrace', 'event', 'shop', 'other', undefined]) {
      expect(ruleTemplates(type).slice(0, 2)).toEqual([
        'Anunță-mă dacă apare un urs',
        'Anunță-mă dacă e foc',
      ]);
    }
  });

  it('a shop and an event then start with a queue at the entrance', () => {
    for (const type of ['shop', 'event']) {
      const list = ruleTemplates(type);
      expect(list[2]).toMatch(/la intrare sunt cel puțin \d+ persoane/);
      expect(list).not.toEqual(ruleTemplates('restaurant'));
    }
  });

  it('every API location type has 5 examples; unknown types get the general set', () => {
    for (const type of ['restaurant', 'terrace', 'event', 'shop', 'other']) {
      const list = ruleTemplates(type);
      expect(list).toHaveLength(5);
      expect(new Set(list).size).toBe(list.length);
    }
    expect(ruleTemplates('pizzerie')).toEqual(ruleTemplates('other'));
    expect(ruleTemplates(undefined)).toEqual(ruleTemplates('other'));
  });

  it('the examples draft the intended rule in the mock', () => {
    const [bearText = '', fireText = '', unservedText = '', handText = '', glassText = ''] =
      ruleTemplates('restaurant');
    const [, , queueText = ''] = ruleTemplates('shop');
    expect(mockRuleFromText(bearText, 'c').all_of[0]).toMatchObject({
      kind: 'object_present',
      objects: ['bear'],
    });
    expect(mockRuleFromText(fireText, 'c').all_of[0].kind).toBe('visual');
    expect(mockRuleFromText(glassText, 'c').all_of[0]).toMatchObject({
      kind: 'object_gone',
      objects: ['wine glass', 'cup'],
    });
    const queue = mockRuleFromText(queueText, 'cam-sala');
    expect(queue.zone_tag).toBe('entrance');
    expect(queue.all_of[0]).toMatchObject({ kind: 'count', min_count: 4 });
    expect(mockRuleFromText(handText, 'c').all_of[0].kind).toBe('pose');
    const unserved = mockRuleFromText(unservedText, 'c');
    expect(unserved.all_of).toContainEqual({ kind: 'absent', role: 'staff', min_duration_s: 120 });
  });
});
