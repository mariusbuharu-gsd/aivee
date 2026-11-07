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
// Classes an open rule ("dacă vine un urs") asks for; used only for object_present, so the
// wording of the older object kinds stays as it was.
const PRESENT_RO: Record<string, string> = {
  ...OBJECT_RO,
  bear: 'un urs',
  dog: 'un câine',
  cat: 'o pisică',
  bird: 'o pasăre',
  horse: 'un cal',
  scissors: 'o foarfecă',
  backpack: 'un rucsac',
  suitcase: 'o valiză',
  handbag: 'o geantă',
  umbrella: 'o umbrelă',
  laptop: 'un laptop',
  'cell phone': 'un telefon',
  bicycle: 'o bicicletă',
};
const OBJECT_KINDS = new Set<Condition['kind']>(['objects_unattended', 'object_gone']);

/** The whole-frame pseudo-zone of rules that name no place (`ANYWHERE_TAG` in contracts). */
export const ANYWHERE = 'anywhere';
export const ANYWHERE_LABEL = 'oriunde în imagine';

/** Open rules: a COCO object appears, or a visual check of the image ("e foc"). */
export const isOpenKind = (k: Condition['kind']) => k === 'object_present' || k === 'visual';
const isOpenRule = (rule: Rule) =>
  rule.all_of.length > 0 && rule.all_of.every((c) => isOpenKind(c.kind));

/** What an open condition looks for: "un urs", "foc". */
export function lookedFor(c: Condition): string {
  if (c.kind === 'object_present') return presentNames(c);
  return c.label_ro?.trim() || c.positive?.[0] || 'o situație';
}
const DISHES = new Set(['cup', 'bottle', 'wine glass', 'bowl', 'fork', 'knife', 'spoon']);

/** "un urs sau un câine" for an object_present condition. */
export function presentNames(c: Condition): string {
  const names = [...new Set((c.objects ?? []).map((o) => PRESENT_RO[o] ?? o))];
  return names.length ? names.join(' sau ') : 'un obiect';
}

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
    case 'object_present':
    case 'visual':
      return lookedFor(c);
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
  if (isOpenRule(rule)) return openChips(rule);
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

/** Unde / Ce caută / Cât timp / Atunci, for a rule made only of open conditions. */
function openChips(rule: Rule): [RuleChip, RuleChip, RuleChip, RuleChip] {
  const all = conditionsWhere(rule, () => true);
  const zone = ZONE_TAGS.find((t) => t.value === rule.zone_tag);
  const where =
    rule.zone_tag === ANYWHERE
      ? ANYWHERE_LABEL
      : rule.zone_tag === 'table'
        ? 'orice masă'
        : (zone?.plural ?? rule.zone_tag);
  const times = all.map(({ c }) => shortDuration(c.min_duration_s) || 'imediat');
  return [
    { key: 'where', label: CHIP_LABEL.where, value: where, fields: [{ kind: 'zone' }] },
    {
      key: 'guest',
      label: 'Ce caută',
      value: all.map(({ c }) => lookedFor(c)).join(', '),
      fields: [],
    },
    {
      key: 'staff',
      label: 'Cât timp',
      value: [...new Set(times)].join(', '),
      fields: all.map(({ index }) => ({ kind: 'duration', index })),
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
    case 'object_present':
      return `apare ${presentNames(c)}${time ? ` (cel puțin ${time})` : ''}`;
    case 'visual':
      return `se vede ${lookedFor(c)}${time ? ` (cel puțin ${time})` : ''}`;
  }
}

/**
 * One line for a rule card, worded per condition kind, e.g.
 * "orice masă · un client așteaptă 2 min și nu vine nimeni de la personal → mesaj pe Telegram"
 * or "orice masă · dispare un pahar de vin (după 1 min pe masă) → notificare pe telefon"
 * or "oriunde în imagine · se vede foc (cel puțin 3 s) → mesaj pe Telegram".
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
  [ANYWHERE]: [`oriunde`, `(?:în|in)\\s+(?:local|restaurant|sal[aă])`],
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
  object_present: [`(?:vine|vin|intr[aă]|apare|apar|are|e|este)\\s+(?:un|o|vreun|vreo)\\s+\\p{L}+`],
  visual: [
    `(?:e|este|iese|ies|apare|izbucne${L}|începe|incepe)\\s+(?:un\\s+|o\\s+)?(?:foc${L}|fum${L}|incendi${L}|flăcăr${L}|ap[aă]${L}(?:\\s+pe\\s+jos)?)`,
    `u[sș][aă]${L}\\s+r[aă]m[aâ]ne\\s+deschis${L}`,
    `(?:foc${L}|fum${L}|incendi${L}|flăcăr${L})`,
  ],
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
