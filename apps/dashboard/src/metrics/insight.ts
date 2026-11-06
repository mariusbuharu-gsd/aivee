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
