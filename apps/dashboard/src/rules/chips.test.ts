import { describe, expect, it } from 'vitest';
import { mockRuleFromText } from '../api/mock';
import type { Rule } from '../contracts';
import { ruleChips, rulePhrases, shortRule } from './chips';
import { ruleTemplates } from './templates';

const table: Rule = {
  id: 'r-1',
  camera_id: 'cam-sala',
  name: 'Masă neservită',
  prompt_ro: '',
  zone_tag: 'table',
  all_of: [
    { kind: 'present', role: 'guest', min_duration_s: 120 },
    { kind: 'absent', role: 'staff', min_duration_s: 120 },
  ],
  action: { type: 'telegram' },
  cooldown_s: 300,
};

const read = (text: string, rule: Rule) =>
  rulePhrases(text, rule).map((p) => [p.chip, text.slice(p.start, p.end)]);

describe('ruleChips', () => {
  it('splits a rule into where, guest, staff and action', () => {
    expect(ruleChips(table).map((c) => [c.label, c.value])).toEqual([
      ['Unde', 'orice masă'],
      ['Client', 'stă 2 min'],
      ['Personal', 'lipsește 2 min'],
      ['Atunci', 'mesaj pe Telegram'],
    ]);
    expect(ruleChips(table)[2].fields).toEqual([{ kind: 'duration', index: 1 }]);
  });

  it('says when a part does not matter', () => {
    const hand: Rule = {
      ...table,
      all_of: [{ kind: 'pose', role: 'guest', pose: 'raised_hand' }],
      action: { type: 'push' },
    };
    expect(ruleChips(hand).map((c) => c.value)).toEqual([
      'orice masă',
      'ridică mâna',
      'nu contează',
      'notificare pe telefon',
    ]);
    expect(ruleChips(hand)[1].fields).toEqual([]);
  });

  it('gives a short line for the rule cards', () => {
    expect(shortRule(table)).toBe(
      'orice masă · client stă 2 min · personal lipsește 2 min → mesaj pe Telegram',
    );
  });
});

describe('rulePhrases', () => {
  it('underlines the phrases behind each part, in text order', () => {
    const text =
      'Dacă la o masă de pe terasă stă un client și nu vine nimeni 2 minute, anunță ospătarul.';
    expect(read(text, table)).toEqual([
      ['where', 'la o masă de pe terasă'],
      ['guest', 'stă un client'],
      ['staff', 'nu vine nimeni 2 minute'],
      ['then', 'anunță ospătarul'],
    ]);
  });

  it('does not underline what the draft did not understand that way', () => {
    const entrance: Rule = { ...table, zone_tag: 'entrance' };
    expect(read('Anunță-mă dacă la o masă stă un client', entrance).map(([c]) => c)).toEqual([
      'then',
      'guest',
    ]);
    expect(read('Ceva fără sens', table)).toEqual([]);
  });

  it('finds at least two parts in every example request', () => {
    for (const type of ['restaurant', 'shop', 'event', 'other']) {
      for (const text of ruleTemplates(type)) {
        const chips = new Set(rulePhrases(text, mockRuleFromText(text, 'c')).map((p) => p.chip));
        expect(chips.size, text).toBeGreaterThanOrEqual(2);
      }
    }
  });
});
