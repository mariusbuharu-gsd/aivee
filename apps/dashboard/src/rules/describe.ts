import type { Condition, Rule } from '../contracts';

const ROLE: Record<NonNullable<Condition['role']>, string> = {
  guest: 'un client',
  staff: 'cineva de la personal',
  any: 'cineva',
};

export const ZONE_TAGS: { value: string; label: string; plural: string }[] = [
  { value: 'table', label: 'Masă', plural: 'fiecare masă' },
  { value: 'entrance', label: 'Intrare', plural: 'intrare' },
  { value: 'staff', label: 'Zonă personal', plural: 'zona personalului' },
];

export const tagLabel = (tag: string) => ZONE_TAGS.find((t) => t.value === tag)?.label ?? tag;

function duration(s: number | undefined): string {
  const v = s ?? 0;
  if (v <= 0) return '';
  if (v % 60 === 0) {
    const m = v / 60;
    return m === 1 ? ' de 1 minut' : ` de ${m} minute`;
  }
  return ` de ${v} secunde`;
}

export function describeCondition(c: Condition): string {
  const who = ROLE[c.role ?? 'any'];
  switch (c.kind) {
    case 'present':
      return `${who} stă în zonă${duration(c.min_duration_s)}`;
    case 'absent':
      return `nu a venit ${who}${duration(c.min_duration_s)}`;
    case 'count':
      return `sunt cel puțin ${c.min_count ?? 1} persoane`;
    case 'pose':
      return `${who} ridică mâna`;
    case 'objects_unattended':
      return `rămân obiecte (${(c.objects ?? []).join(', ') || 'vase'}) fără nimeni${duration(c.min_duration_s)}`;
  }
}

const ACTION: Record<Rule['action']['type'], string> = {
  telegram: 'mesaj pe Telegram',
  push: 'notificare pe telefon',
  webhook: 'webhook',
};

/** Romanian one-liner for the "Ce am înțeles" panel. */
export function describeRule(rule: Rule): string {
  const where =
    ZONE_TAGS.find((t) => t.value === rule.zone_tag)?.plural ?? `zona „${rule.zone_tag}”`;
  const when = rule.all_of.map(describeCondition).join(' și ');
  return `La ${where}, când ${when} → ${ACTION[rule.action.type]}.`;
}
