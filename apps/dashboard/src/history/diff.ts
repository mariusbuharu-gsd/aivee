import { duration } from '../alerts/format';
import { ROLE_LABEL } from '../auth/session';
import type { Role } from '../api/client';
import type { Condition } from '../contracts';
import { describeCondition } from '../rules/describe';

const LABELS: Record<string, string> = {
  name: 'Nume',
  prompt_ro: 'Cererea',
  enabled: 'Activă',
  cooldown_s: 'Pauză între alerte',
  all_of: 'Condiții',
  zone_tag: 'Tipul zonei',
  action: 'Trimite pe',
  role: 'Rol',
  zones: 'Zone',
  source: 'Sursă',
  device: 'Dispozitiv',
  type: 'Tip',
  telegram_chat_id: 'Chat Telegram',
  telegram_chat_title: 'Grup Telegram',
  email: 'Email',
};

const WHO: Record<string, string> = {
  staff: 'de la personal',
  guest: 'dintre clienți',
  any: '',
};

/** A condition's time as a person says it: "nimeni de la personal", "clienți în zonă". */
function conditionLabel(kind: string, role: string | undefined): string | null {
  switch (kind) {
    case 'absent':
      return `Nimeni ${WHO[role ?? 'any'] ?? ''}`.trim();
    case 'present':
      return role === 'staff'
        ? 'Personal în zonă'
        : role === 'guest'
          ? 'Clienți în zonă'
          : 'Cineva în zonă';
    case 'objects_unattended':
      return 'Obiecte fără nimeni';
    case 'object_gone':
      return 'Obiect dispărut';
    default:
      return null;
  }
}

/** "absent_staff_s" (a flattened condition time) → "Nimeni de la personal". */
function label(key: string): string | null {
  if (key in LABELS) return LABELS[key] ?? null;
  const m = /^([a-z_]+?)_(staff|guest|any)_s$/.exec(key);
  return m ? conditionLabel(m[1] ?? '', m[2]) : null;
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v);

const isCondition = (v: unknown): v is Condition => isRecord(v) && typeof v.kind === 'string';

/** "5 min", "1 min 30 s", "45 s". */
function time(s: number): string {
  return s >= 60 && s % 60 === 0 ? `${s / 60} min` : duration(s);
}

/** A value as a person would say it: "da", "2 min", "Masa 1, Masa 2", "Manager". */
export function say(key: string, v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'boolean') return v ? 'da' : 'nu';
  if (typeof v === 'number') return key.endsWith('_s') ? time(v) : String(v);
  if (key === 'role' && typeof v === 'string' && v in ROLE_LABEL) return ROLE_LABEL[v as Role];
  if (typeof v === 'string') return v;
  if (Array.isArray(v)) {
    const names = v.map((x) => (isRecord(x) && typeof x.name === 'string' ? x.name : null));
    if (names.every((n) => n !== null)) return names.join(', ') || '—';
    if (key === 'all_of' && v.every(isCondition)) return v.map(describeCondition).join(' și ');
    return `${v.length} elemente`;
  }
  if (isRecord(v)) {
    if (typeof v.type === 'string') return v.type;
    return Object.keys(v).join(', ');
  }
  return String(v);
}

export interface Change {
  label: string;
  from: string;
  to: string;
}

/**
 * A rule's conditions, changed in place (same kinds, other times): one line per changed time,
 * "Nimeni de la personal: 5 min → 2 min". Null when the shape changed; then the whole list
 * is said in words.
 */
function conditionChanges(before: unknown, after: unknown): Change[] | null {
  if (!Array.isArray(before) || !Array.isArray(after) || before.length !== after.length) {
    return null;
  }
  const out: Change[] = [];
  for (let i = 0; i < before.length; i++) {
    const b: unknown = before[i];
    const a: unknown = after[i];
    if (!isCondition(b) || !isCondition(a) || b.kind !== a.kind || b.role !== a.role) return null;
    if (JSON.stringify(b) === JSON.stringify(a)) continue;
    const { min_duration_s: bs, ...bRest } = b;
    const { min_duration_s: as, ...aRest } = a;
    const name = conditionLabel(a.kind, a.role);
    if (JSON.stringify(bRest) !== JSON.stringify(aRest) || !name) return null;
    out.push({ label: name, from: say('_s', bs ?? 0), to: say('_s', as ?? 0) });
  }
  return out;
}

/**
 * Top-level fields that differ between `before` and `after`, in words. Fields without a
 * human name are left out here; the raw values stay under "Detalii tehnice".
 */
export function describeChanges(before: unknown, after: unknown): Change[] {
  if (!isRecord(before) && !isRecord(after)) {
    return before === after
      ? []
      : [{ label: 'Valoare', from: say('', before), to: say('', after) }];
  }
  const b = isRecord(before) ? before : {};
  const a = isRecord(after) ? after : {};
  const keys = [...new Set([...Object.keys(b), ...Object.keys(a)])].filter(
    (k) => k !== 'id' && k !== 'camera_id' && JSON.stringify(b[k]) !== JSON.stringify(a[k]),
  );
  return keys.flatMap((k) => {
    if (k === 'all_of') {
      const inPlace = conditionChanges(b[k], a[k]);
      if (inPlace) return inPlace;
    }
    const name = label(k);
    return name ? [{ label: name, from: say(k, b[k]), to: say(k, a[k]) }] : [];
  });
}
