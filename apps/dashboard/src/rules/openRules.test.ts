import { describe, expect, it } from 'vitest';
import { MockApi, mockRuleFromText } from '../api/mock';
import type { Rule } from '../contracts';
import { ruleChips, rulePhrases, shortRule } from './chips';
import { describeRule } from './describe';

const fire: Rule = {
  id: 'r-foc',
  camera_id: 'cam-sala',
  name: 'Foc în imagine',
  prompt_ro: 'dacă e foc',
  zone_tag: 'anywhere',
  all_of: [
    {
      kind: 'visual',
      role: 'any',
      min_duration_s: 3,
      positive: ['a photo of fire', 'flames'],
      negative: ['a photo of a room'],
      threshold: 0.5,
      crop: 'frame',
      label_ro: 'foc',
    },
  ],
  action: { type: 'telegram' },
  cooldown_s: 120,
};

const bear: Rule = {
  ...fire,
  id: 'r-urs',
  prompt_ro: 'anunță-mă dacă vine un urs',
  all_of: [{ kind: 'object_present', role: 'any', objects: ['bear'], min_duration_s: 2 }],
};

const read = (text: string, rule: Rule) =>
  rulePhrases(text, rule).map((p) => [p.chip, text.slice(p.start, p.end)]);

describe('open rules on the rule card', () => {
  it('reads a visual rule as Unde / Ce caută / Cât timp / Atunci', () => {
    expect(ruleChips(fire).map((c) => [c.label, c.value])).toEqual([
      ['Unde', 'oriunde în imagine'],
      ['Ce caută', 'foc'],
      ['Cât timp', '3 s'],
      ['Atunci', 'mesaj pe Telegram'],
    ]);
    expect(ruleChips(fire)[2].fields).toEqual([{ kind: 'duration', index: 0 }]);
  });

  it('names the COCO object of an object_present rule in Romanian', () => {
    expect(ruleChips(bear).map((c) => c.value)).toEqual([
      'oriunde în imagine',
      'un urs',
      '2 s',
      'mesaj pe Telegram',
    ]);
  });

  it('words the card sentence per kind', () => {
    expect(shortRule(fire)).toBe(
      'oriunde în imagine · se vede foc (cel puțin 3 s) → mesaj pe Telegram',
    );
    expect(shortRule(bear)).toBe(
      'oriunde în imagine · apare un urs (cel puțin 2 s) → mesaj pe Telegram',
    );
    const dog: Rule = {
      ...bear,
      zone_tag: 'entrance',
      all_of: [{ kind: 'object_present', role: 'any', objects: ['dog'], min_duration_s: 0 }],
    };
    expect(shortRule(dog)).toBe('intrare · apare un câine → mesaj pe Telegram');
  });

  it('falls back to the first prompt when the visual condition has no Romanian label', () => {
    const unlabeled: Rule = { ...fire, all_of: [{ ...fire.all_of[0], label_ro: '' }] };
    expect(ruleChips(unlabeled)[1].value).toBe('a photo of fire');
  });

  it('describes the whole-frame rule and the extra check in one line', () => {
    expect(describeRule(fire)).toBe(
      'La oricare loc din imagine, când se vede foc de 3 secunde (verificat pe imagine înainte de alertă) → mesaj pe Telegram.',
    );
  });

  it('underlines what the owner typed', () => {
    expect(read('dacă e foc', fire)).toEqual([['guest', 'e foc']]);
    expect(read('anunță-mă dacă vine un urs', bear)).toEqual([
      ['then', 'anunță-mă'],
      ['guest', 'vine un urs'],
    ]);
  });
});

describe('mock', () => {
  it('turns open requests into open rules', () => {
    const r = mockRuleFromText('anunță-mă dacă vine un urs', 'cam-sala');
    expect([r.zone_tag, r.all_of[0].kind, r.all_of[0].objects, r.cooldown_s]).toEqual([
      'anywhere',
      'object_present',
      ['bear'],
      120,
    ]);
    expect(mockRuleFromText('dacă e foc', 'cam-sala').all_of[0].kind).toBe('visual');
  });

  it('seeds one visual and one object_present rule', async () => {
    const rules = await new MockApi({ latencyMs: 0, autoplay: false }).listRules();
    const kinds = rules.flatMap((r) => r.all_of.map((c) => c.kind));
    expect(kinds).toContain('visual');
    expect(kinds).toContain('object_present');
  });
});
