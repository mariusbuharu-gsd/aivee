import type { Condition, Rule } from '../contracts';
import { ZONE_TAGS } from './describe';

// A rule as the four parts a manager reads and corrects: where, the guest, the staff, the action.
// `phrases` finds, in the sentence the manager typed, the words that led to each part, so the
// "eyes read the rule" moment can underline them. The translator does not return spans, so this
// only underlines a phrase that names what the draft actually holds (a "masă" for a table rule,
// "nu vine nimeni" for an absent-staff condition); anything else stays plain.

export type ChipKey = 'where' | 'guest' | 'staff' | 'then';

export const CHIP_KEYS: ChipKey[] = ['where', 'guest', 'staff', 'then'];

export const CHIP_LABEL: Record<ChipKey, string> = {
  where: 'Unde',
  guest: 'Client',
  staff: 'Personal',
  then: 'Atunci',
};

/** A value the per-chip editor can change. */
export type ChipField =
  | { kind: 'zone' }
  | { kind: 'duration'; index: number }
  | { kind: 'count'; index: number }
  | { kind: 'cooldown' };

export interface RuleChip {
  key: ChipKey;
  label: string;
  value: string;
  fields: ChipField[];
}

// COCO class names (Condition.objects) in Romanian, with the indefinite article; the same
// pairs the translator prompt uses (apps/api rules/prompt.py). Unknown labels stay as COCO.
const OBJECT_RO: Record<string, string> = {
  'wine glass': 'un pahar de vin',
  cup: 'o ceașcă',
  bottle: 'o sticlă',
  bowl: 'un bol',
  fork: 'o furculiță',
  knife: 'un cuțit',
  spoon: 'o lingură',
};
const OBJECT_KINDS = new Set<Condition['kind']>(['objects_unattended', 'object_gone']);
const DISHES = new Set(['cup', 'bottle', 'wine glass', 'bowl', 'fork', 'knife', 'spoon']);

/** "un pahar de vin sau o ceașcă"; COCO labels without a Romanian name are kept as they are. */
export function objectNames(c: Condition, join = ' sau '): string {
  const names = [...new Set((c.objects ?? []).map((o) => OBJECT_RO[o] ?? o))];
  return names.length ? names.join(join) : 'un obiect';
}

const ACTION_RO: Record<Rule['action']['type'], string> = {
  telegram: 'mesaj pe Telegram',
  push: 'notificare pe telefon',
  webhook: 'webhook',
};

/** "2 min", "45 s", or "" for no duration. */
export function shortDuration(s: number | undefined): string {
  const v = Math.max(0, Math.round(s ?? 0));
  if (!v) return '';
  return v % 60 === 0 ? `${v / 60} min` : `${v} s`;
}

const withTime = (text: string, s: number | undefined) =>
  [text, shortDuration(s)].filter(Boolean).join(' ');

function guestPart(c: Condition): string {
  switch (c.kind) {
    case 'present':
      return withTime('stă', c.min_duration_s);
    case 'absent':
      return withTime('lipsește', c.min_duration_s);
    case 'count':
      return `cel puțin ${c.min_count ?? 1} persoane`;
    case 'pose':
      return 'ridică mâna';
    case 'objects_unattended':
      return withTime('vase lăsate', c.min_duration_s);
    case 'object_gone':
      return `dispare ${objectNames(c)}`;
  }
}

function staffPart(c: Condition): string {
  switch (c.kind) {
    case 'absent':
      return withTime('lipsește', c.min_duration_s);
    case 'present':
      return withTime('e în zonă', c.min_duration_s);
    case 'count':
      return `cel puțin ${c.min_count ?? 1}`;
    default:
      return guestPart(c);
  }
}

type Indexed = { c: Condition; index: number };

function fieldsOf(conditions: Indexed[]): ChipField[] {
  return conditions.flatMap(({ c, index }): ChipField[] => {
    if (c.kind === 'count') return [{ kind: 'count', index }];
    return c.min_duration_s === undefined ? [] : [{ kind: 'duration', index }];
  });
}

const conditionsWhere = (rule: Rule, pick: (c: Condition) => boolean): Indexed[] =>
  rule.all_of.flatMap((c, index) => (pick(c) ? [{ c, index }] : []));

const isStaff = (c: Condition) => c.role === 'staff';

/** The four chips for a rule, in reading order. */
export function ruleChips(rule: Rule): [RuleChip, RuleChip, RuleChip, RuleChip] {
  const guest = conditionsWhere(rule, (c) => !isStaff(c));
  const staff = conditionsWhere(rule, isStaff);
  const zone = ZONE_TAGS.find((t) => t.value === rule.zone_tag);
  const where = rule.zone_tag === 'table' ? 'orice masă' : (zone?.plural ?? rule.zone_tag);
  return [
    { key: 'where', label: CHIP_LABEL.where, value: where, fields: [{ kind: 'zone' }] },
    {
      key: 'guest',
      // An object rule (unattended dishes, a glass that disappears) is not about a guest.
      label:
        guest.length > 0 && guest.every(({ c }) => OBJECT_KINDS.has(c.kind))
          ? 'Obiect'
          : CHIP_LABEL.guest,
      value: guest.map(({ c }) => guestPart(c)).join(', ') || 'oricine',
      fields: fieldsOf(guest),
    },
    {
      key: 'staff',
      label: CHIP_LABEL.staff,
      value: staff.map(({ c }) => staffPart(c)).join(', ') || 'nu contează',
      fields: fieldsOf(staff),
    },
    {
      key: 'then',
      label: CHIP_LABEL.then,
      value: ACTION_RO[rule.action.type],
      fields: [{ kind: 'cooldown' }],
    },
  ];
}

const WHO: Record<NonNullable<Condition['role']>, string> = {
  guest: 'un client',
  staff: 'cineva de la personal',
  any: 'cineva',
};
const NOBODY: Record<NonNullable<Condition['role']>, string> = {
  guest: 'niciun client',
  staff: 'nimeni de la personal',
  any: 'nimeni',
};

/** " de 2 min", or "" with no duration. */
const forTime = (s: number | undefined) => (shortDuration(s) ? ` de ${shortDuration(s)}` : '');

/** One condition as a clause of the card sentence, worded for its kind. */
export function conditionClause(c: Condition, zoneTag: string): string {
  const role = c.role ?? 'any';
  const time = shortDuration(c.min_duration_s);
  const onTable = zoneTag === 'table';
  switch (c.kind) {
    case 'present':
      return `${WHO[role]} stă${forTime(c.min_duration_s)}`;
    case 'absent':
      return `nu vine ${NOBODY[role]}${forTime(c.min_duration_s)}`;
    case 'count':
      return `cel puțin ${c.min_count ?? 1} persoane${zoneTag === 'entrance' ? ' la coadă' : ''}`;
    case 'pose':
      return `${WHO[role === 'any' ? 'guest' : role]} ridică mâna`;
    case 'objects_unattended':
      if (onTable && (c.objects ?? []).every((o) => DISHES.has(o))) {
        return `masa rămâne nedebarasată${forTime(c.min_duration_s)}`;
      }
      return `rămâne ${objectNames(c)} fără nimeni lângă${forTime(c.min_duration_s)}`;
    case 'object_gone':
      return `dispare ${objectNames(c)}${time ? ` (după ${time} ${onTable ? 'pe masă' : 'în zonă'})` : ''}`;
  }
}

/**
 * One line for a rule card, worded per condition kind, e.g.
 * "orice masă · un client așteaptă 2 min și nu vine nimeni de la personal → mesaj pe Telegram"
 * or "orice masă · dispare un pahar de vin (după 1 min pe masă) → notificare pe telefon".
 */
export function shortRule(rule: Rule): string {
  const [where, , , then] = ruleChips(rule);
  const [first, second, ...rest] = rule.all_of;
  // The default wait rule: a guest is there and staff has not come, for the same time.
  const wait =
    first?.kind === 'present' &&
    first.role === 'guest' &&
    second?.kind === 'absent' &&
    second.role === 'staff' &&
    rest.length === 0 &&
    (first.min_duration_s ?? 0) === (second.min_duration_s ?? 0);
  const what = wait
    ? `un client așteaptă ${shortDuration(first.min_duration_s) || 'în zonă'} și nu vine nimeni de la personal`
    : rule.all_of.map((c) => conditionClause(c, rule.zone_tag)).join(' și ');
  return `${where.value} · ${what} → ${then.value}`;
}

// ---------------------------------------------------------------------------------------------
// Phrases

export interface Phrase {
  start: number;
  end: number;
  chip: ChipKey;
}

const L = '\\p{L}*';
const START = '(?<!\\p{L})';
const AMOUNT = `(?:\\d+|un|o|una|două|doua|trei|cinci|zece)\\s+(?:minut${L}|min|secund${L}|sec)`;
const TIME = `(?:\\s+(?:de|timp de|mai mult de|peste|în|in)?\\s*${AMOUNT})?`;

const WHERE: Record<string, string[]> = {
  table: [
    `(?:(?:la|pe|de pe|de la)\\s+)?(?:(?:o|fiecare|orice|vreo|nicio|una)\\s+)?mas[aăe]${L}(?:\\s+de\\s+pe\\s+teras${L})?`,
  ],
  entrance: [`(?:(?:la|de la)\\s+)?(?:intrare${L}|u[sș][aă]${L})`],
  staff: [`(?:(?:în|in|la)\\s+)?zon${L}\\s+(?:de\\s+)?personal${L}`, `bucătări${L}`],
};

const GUEST_WHO = `(?:client${L}|invitat${L}|cineva|oaspe${L})`;
const GUEST: Record<Condition['kind'], string[]> = {
  present: [
    `(?:st[aă]${L}|a[sș]teapt${L}|e)\\s+(?:(?:un|o|vreun|niște)\\s+)?${GUEST_WHO}(?:\\s+mai mult de\\s+${AMOUNT})?`,
    `(?:(?:un|o|vreun|niște)\\s+)?${GUEST_WHO}\\s+(?:st[aă]${L}|a[sș]teapt${L})${TIME}`,
    `(?:(?:un|o|vreun|niște)\\s+)?(?:client${L}|invitat${L})`,
  ],
  absent: [`(?:(?:un|o|vreun)\\s+)?(?:client${L}|invitat${L})`],
  count: [
    `(?:(?:cel puțin|cel putin|peste|minim|mai mult de)\\s+)?\\d+\\s+(?:persoane|oameni|clien${L}|invita${L})(?:\\s+la\\s+coad${L})?`,
    `coad${L}`,
  ],
  pose: [
    `(?:(?:un|o|vreun)\\s+)?${GUEST_WHO}\\s+(?:${L}\\s+)?ridic${L}\\s+m[aâ]n${L}`,
    `ridic${L}\\s+m[aâ]n${L}`,
    `(?:cheam${L}|face semn)`,
  ],
  objects_unattended: [
    `(?:r[aă]m[aâ]n${L}\\s+)?nedebarasat${L}${TIME}`,
    `(?:vase${L}|pahare${L}|farfuri${L}|sticl${L})`,
  ],
  object_gone: [`dispare\\s+(?:(?:un|o)\\s+)?\\p{L}+`],
};

const STAFF_WHO = `(?:nimeni|niciun${L}|vreun${L}|ospătar${L}|ospatar${L}|chelner${L})`;
const STAFF: Partial<Record<Condition['kind'], string[]>> = {
  absent: [
    `nu\\s+(?:vine|trece|a venit|a trecut|e|este|se apropie|apare|a apărut)\\s+${STAFF_WHO}(?:\\s+de la personal)?${TIME}`,
    `fără\\s+(?:ospătar${L}|personal${L}|nimeni)`,
  ],
  present: [`(?:ospătar${L}|chelner${L}|personal${L})`],
};

const THEN = [
  `anun[țţt]${L}(?:-(?:m[aă]|ne))?(?:\\s+(?:ospătar${L}|ospatar${L}|chelner${L}|manager${L}|șef${L}))?`,
  `trimite${L}(?:\\s+(?:un|o))?\\s+(?:mesaj${L}|notificare${L})`,
  `d[aă]-mi de [șs]tire`,
];

const DURATION = `(?:(?:de|timp de|mai mult de|peste)\\s+)?${AMOUNT}`;

function find(text: string, patterns: string[], chip: ChipKey): Phrase[] {
  return patterns.flatMap((p) =>
    [...text.matchAll(new RegExp(`${START}${p}(?!\\p{L})`, 'giu'))].map((m) => ({
      start: m.index,
      end: m.index + m[0].length,
      chip,
    })),
  );
}

/**
 * Non-overlapping phrases of `text` that name a part of `rule`, in text order. Only patterns for
 * what the rule holds are tried, so a sentence the translator read differently is not underlined.
 */
export function rulePhrases(text: string, rule: Rule): Phrase[] {
  const guest = rule.all_of.filter((c) => !isStaff(c));
  const staff = rule.all_of.filter(isStaff);
  const found = [
    ...find(text, WHERE[rule.zone_tag] ?? [], 'where'),
    ...guest.flatMap((c) => find(text, GUEST[c.kind], 'guest')),
    ...staff.flatMap((c) => find(text, STAFF[c.kind] ?? [], 'staff')),
    ...find(text, THEN, 'then'),
  ];
  // A stray duration ("de 2 minute") belongs to the part that has one, staff first.
  const timed = staff.some((c) => c.min_duration_s)
    ? 'staff'
    : guest.some((c) => c.min_duration_s)
      ? 'guest'
      : null;
  if (timed) found.push(...find(text, [DURATION], timed));

  // Longest first, then keep what does not overlap something already kept.
  found.sort((a, b) => b.end - b.start - (a.end - a.start) || a.start - b.start);
  const kept: Phrase[] = [];
  for (const p of found) {
    if (p.end > p.start && kept.every((k) => p.end <= k.start || p.start >= k.end)) kept.push(p);
  }
  return kept.sort((a, b) => a.start - b.start);
}
