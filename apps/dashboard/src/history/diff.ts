import { duration } from '../alerts/format';
import { ROLE_LABEL } from '../auth/session';
import type { Role } from '../api/client';

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
  email: 'Email',
};

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v);

/** A value as a person would say it: "da", "2 min 0 s", "Masa 1, Masa 2", "Manager". */
export function say(key: string, v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'boolean') return v ? 'da' : 'nu';
  if (typeof v === 'number') return key.endsWith('_s') ? duration(v) : String(v);
  if (key === 'role' && typeof v === 'string' && v in ROLE_LABEL) return ROLE_LABEL[v as Role];
  if (typeof v === 'string') return v;
  if (Array.isArray(v)) {
    const names = v.map((x) => (isRecord(x) && typeof x.name === 'string' ? x.name : null));
    if (names.every((n) => n !== null)) return names.join(', ') || '—';
    if (key === 'all_of') {
      return v
        .map((c) =>
          isRecord(c) && typeof c.min_duration_s === 'number' ? duration(c.min_duration_s) : '…',
        )
        .join(' + ');
    }
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

/** Top-level fields that differ between `before` and `after`, in words. */
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
  return keys.map((k) => ({ label: LABELS[k] ?? k, from: say(k, b[k]), to: say(k, a[k]) }));
}
