import type { AlertItem } from './fold';

/** Seconds the alert has been (or was) open. */
export function openFor(a: AlertItem, now = Date.now()): number {
  const end = a.closed_at ? Date.parse(a.closed_at) : now;
  return Math.max(0, (end - Date.parse(a.opened_at)) / 1000);
}

/** What a closed row's duration bar is measured against. */
export interface AlertLimit {
  seconds: number;
  /** True for the rule's own threshold, false for a fallback scale (longest alert of the day). */
  ofRule: boolean;
}

/**
 * The rule's wait threshold in seconds: the longest `min_duration_s` of its waiting conditions.
 * Null for instant rules (a raised hand). `object_gone` is skipped: its duration is how long the
 * object stood there before vanishing, not how long anyone may wait.
 */
export function ruleLimitS(rule: {
  all_of: { kind?: string; min_duration_s?: number }[];
}): number | null {
  const waits = rule.all_of.filter((c) => c.kind !== 'object_gone');
  const s = Math.max(0, ...waits.map((c) => c.min_duration_s ?? 0));
  return s > 0 ? s : null;
}
