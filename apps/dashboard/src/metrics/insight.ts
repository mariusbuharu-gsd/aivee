import { duration } from '../alerts/format';
import type { Rule } from '../contracts';

/** The period phrases the Metrici page uses, keyed by its length in days. */
const NOW: Record<number, string> = {
  1: 'azi',
  7: 'în ultimele 7 zile',
  30: 'în ultimele 30 de zile',
};
const BEFORE: Record<number, string> = {
  1: 'ieri',
  7: 'în cele 7 zile dinainte',
  30: 'în cele 30 de zile dinainte',
};

export const periodPhrase = (days: number) => NOW[days] ?? `în ultimele ${days} zile`;

export interface Headline {
  /** The median wait, or null when no alert in the period has one. */
  value: string | null;
  /** Everything after the value, including the comparison and the full stop. */
  rest: string;
  tone: 'better' | 'worse' | 'same' | 'none';
}

/**
 * The sentence that draws the conclusion: how long guests waited and whether that is
 * better or worse than the same span just before. Shorter is better.
 */
export function headline(days: number, now: number | null, before: number | null): Headline {
  const when = periodPhrase(days);
  if (now === null) {
    return { value: null, rest: `Nicio alertă cu așteptare măsurată ${when}.`, tone: 'none' };
  }
  const value = duration(now);
  if (before === null) return { value, rest: ` ${when}.`, tone: 'none' };
  const d = Math.round(now - before);
  const prev = BEFORE[days] ?? 'în perioada dinainte';
  if (Math.abs(d) < 1) return { value, rest: ` ${when}, la fel ca ${prev}.`, tone: 'same' };
  const by = duration(Math.abs(d));
  return d < 0
    ? { value, rest: ` ${when}, cu ${by} mai puțin decât ${prev}.`, tone: 'better' }
    : { value, rest: ` ${when}, cu ${by} mai mult decât ${prev}.`, tone: 'worse' };
}

/**
 * The owner's own bar for "too long": the time of the unserved-table rule (nobody from staff
 * came for N seconds). A rule named like "Masă neservită" wins; otherwise the strictest
 * enabled staff-absence rule. Null when there is none, so the chart draws no line.
 */
export function serviceTarget(rules: Rule[]): number | null {
  const absence = (r: Rule) =>
    r.all_of.find((c) => c.kind === 'absent' && c.role === 'staff' && (c.min_duration_s ?? 0) > 0)
      ?.min_duration_s ?? null;
  const candidates = rules
    .filter((r) => r.enabled !== false)
    .map((r) => ({ named: /neservit/i.test(r.name), s: absence(r) }))
    .filter((c): c is { named: boolean; s: number } => c.s !== null);
  const pool = candidates.some((c) => c.named) ? candidates.filter((c) => c.named) : candidates;
  return pool.length ? Math.min(...pool.map((c) => c.s)) : null;
}

export type BarTone = 'slowest' | 'over' | 'under' | 'empty';

/**
 * How each day's bar is drawn: the slowest day stands out, days over the target are full,
 * days under it are light. Without a target every measured day counts as "over".
 */
export function barTones(waits: (number | null)[], target: number | null): BarTone[] {
  const measured = waits.filter((w): w is number => w !== null);
  const slowest = measured.length ? waits.indexOf(Math.max(...measured)) : -1;
  return waits.map((w, i) => {
    if (w === null) return 'empty';
    if (i === slowest) return 'slowest';
    return target === null || w > target ? 'over' : 'under';
  });
}

/** "1:57", "45 s": short enough to sit above a narrow bar. */
export function shortDuration(s: number): string {
  const v = Math.max(0, Math.round(s));
  return v < 60 ? `${v} s` : `${Math.floor(v / 60)}:${String(v % 60).padStart(2, '0')}`;
}

export interface Target {
  seconds: number;
  /** `location`: the owner set it on Metrici; `rule`: borrowed from the unserved-table rule. */
  source: 'location' | 'rule';
}

/** The location's own service target when set, else the rule's time, else none. */
export function pickTarget(own: number | null | undefined, rule: number | null): Target | null {
  if (own != null) return { seconds: own, source: 'location' };
  return rule === null ? null : { seconds: rule, source: 'rule' };
}

export const TARGET_MAX_S = 3600;

/** Minutes and seconds typed in the target popover → seconds (1 s – 60 min), or null. */
export function targetSeconds(min: string, sec: string): number | null {
  const part = (v: string) => (v.trim() === '' ? 0 : /^\d+$/.test(v.trim()) ? Number(v) : NaN);
  const m = part(min);
  const s = part(sec);
  if (Number.isNaN(m) || Number.isNaN(s) || s > 59) return null;
  const total = m * 60 + s;
  return total >= 1 && total <= TARGET_MAX_S ? total : null;
}

const WEEKDAYS = ['luni', 'marți', 'miercuri', 'joi', 'vineri', 'sâmbătă', 'duminică'];
export const WEEKDAYS_SHORT = ['lun', 'mar', 'mie', 'joi', 'vin', 'sâm', 'dum'];

interface Cell {
  alerts: number;
  wait_median_s: number | null;
}

/** The hours worth a column: first to last with any alert, else the usual 10–23. */
export function heatHours(cells: Cell[][]): number[] {
  const used = Array.from({ length: 24 }, (_, h) => h).filter((h) =>
    cells.some((row) => (row[h]?.alerts ?? 0) > 0),
  );
  const lo = used[0] ?? 10;
  const hi = used.at(-1) ?? 23;
  return Array.from({ length: hi - lo + 1 }, (_, i) => lo + i);
}

/** "marți 20:00 · 4 alerte · de obicei 1 min 50 s". Weekday 0 is Monday. */
export function heatLabel(weekday: number, hour: number, c: Cell): string {
  const when = `${WEEKDAYS[weekday] ?? ''} ${String(hour).padStart(2, '0')}:00`;
  if (c.alerts === 0) return `${when} · nicio alertă`;
  const count = c.alerts === 1 ? '1 alertă' : `${c.alerts} alerte`;
  const wait = c.wait_median_s === null ? '' : ` · de obicei ${duration(c.wait_median_s)}`;
  return `${when} · ${count}${wait}`;
}

/** 0 for an empty cell, 1–4 relative to the busiest cell. */
export function heatLevel(alerts: number, max: number): number {
  if (alerts <= 0 || max <= 0) return 0;
  return Math.min(4, Math.max(1, Math.ceil((alerts / max) * 4)));
}
