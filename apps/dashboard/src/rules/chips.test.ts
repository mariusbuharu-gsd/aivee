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

  it('labels an object rule "Obiect", not "Client"', () => {
    const gone: Rule = {
      ...table,
      all_of: [{ kind: 'object_gone', role: 'any', objects: ['wine glass'], min_duration_s: 60 }],
    };
    expect(ruleChips(gone)[1]).toMatchObject({ label: 'Obiect', value: 'dispare un pahar de vin' });
  });
});

describe('shortRule', () => {
  const with_ = (all_of: Rule['all_of'], patch: Partial<Rule> = {}): Rule => ({
    ...table,
    all_of,
    ...patch,
  });

  it('the default wait rule', () => {
    expect(shortRule(table)).toBe(
      'orice masă · un client așteaptă 2 min și nu vine nimeni de la personal → mesaj pe Telegram',
    );
  });

  it('a wait with different times says each one', () => {
    const rule = with_([
      { kind: 'present', role: 'guest', min_duration_s: 60 },
      { kind: 'absent', role: 'staff', min_duration_s: 120 },
    ]);
    expect(shortRule(rule)).toBe(
      'orice masă · un client stă de 1 min și nu vine nimeni de la personal de 2 min → mesaj pe Telegram',
    );
  });

  it('a raised hand', () => {
    const rule = with_([{ kind: 'pose', role: 'guest', pose: 'raised_hand' }], {
      action: { type: 'push' },
    });
    expect(shortRule(rule)).toBe('orice masă · un client ridică mâna → notificare pe telefon');
  });

  it('a table not cleared', () => {
    const rule = with_([
      {
        kind: 'objects_unattended',
        role: 'any',
        objects: ['cup', 'bowl', 'bottle'],
        min_duration_s: 300,
      },
    ]);
    expect(shortRule(rule)).toBe(
      'orice masă · masa rămâne nedebarasată de 5 min → mesaj pe Telegram',
    );
  });

  it('unattended objects that are not dishes', () => {
    const rule = with_(
      [{ kind: 'objects_unattended', role: 'any', objects: ['backpack'], min_duration_s: 120 }],
      { zone_tag: 'entrance' },
    );
    expect(shortRule(rule)).toBe(
      'intrare · rămâne backpack fără nimeni lângă de 2 min → mesaj pe Telegram',
    );
  });

  it('an object that disappears, in Romanian', () => {
    const rule = with_(
      [{ kind: 'object_gone', role: 'any', objects: ['wine glass'], min_duration_s: 60 }],
      { action: { type: 'push' } },
    );
    expect(shortRule(rule)).toBe(
      'orice masă · dispare un pahar de vin (după 1 min pe masă) → notificare pe telefon',
    );
  });

  it('a queue at the entrance', () => {
    const rule = with_(
      [
        { kind: 'count', role: 'guest', min_count: 4 },
        { kind: 'absent', role: 'staff', min_duration_s: 0 },
      ],
      { zone_tag: 'entrance' },
    );
    expect(shortRule(rule)).toBe(
      'intrare · cel puțin 4 persoane la coadă și nu vine nimeni de la personal → mesaj pe Telegram',
    );
  });

  it('someone present in the staff zone', () => {
    const rule = with_([{ kind: 'present', role: 'any', min_duration_s: 30 }], {
      zone_tag: 'staff',
    });
    expect(shortRule(rule)).toBe('zona personalului · cineva stă de 30 s → mesaj pe Telegram');
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
