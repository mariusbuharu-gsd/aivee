import type { AuditEntry } from '../api/client';

/** The lifecycle stages an alert's audit entries record, in the order they happen. */
export type Stage = 'opened' | 'acknowledged' | 'realerted' | 'arrived' | 'closed';
const STAGES: readonly Stage[] = ['opened', 'acknowledged', 'realerted', 'arrived', 'closed'];

export interface Step {
  stage: Stage;
  at: string;
  /** Seconds after the first known entry of the alert. */
  offset_s: number;
  entry: AuditEntry;
}

/** One alert, folded from its `alert.*` entries: one row instead of four. */
export interface AlertThread {
  type: 'thread';
  /** The alert (event) id. */
  id: string;
  /** Zone label ("Masa 1"). */
  label: string;
  /** What the alert was about, from its opening entry when that is loaded. */
  title: string;
  /** The first known entry's time. */
  start: string;
  /** The newest entry's time; the thread sits where that entry would. */
  latest: string;
  steps: Step[];
  /** Opened → closed, in seconds; null while either end is missing. */
  duration_s: number | null;
  /** Chronological, oldest first. */
  entries: AuditEntry[];
}

export type HistoryItem = { type: 'entry'; entry: AuditEntry } | AlertThread;

const stageOf = (e: AuditEntry): Stage | null => {
  if (e.target?.type !== 'alert' || !e.kind.startsWith('alert.')) return null;
  const s = e.kind.slice('alert.'.length) as Stage;
  return STAGES.includes(s) ? s : null;
};

const ms = (iso: string) => Date.parse(iso);

/** "Alertă nouă: Masa 1: nimeni…" (the API's device entry) reads as "Masa 1: nimeni…". */
const titleOf = (summary: string) => summary.replace(/^Alertă nouă:\s*/, '');

/**
 * Folds the alert lifecycle entries of the same alert into one thread, kept at the place of
 * its newest entry; every other entry stays as it is. Input and output are newest first.
 * A lone alert entry (say, a filter on one person) stays a plain entry: nothing to fold.
 */
export function foldHistory(items: AuditEntry[]): HistoryItem[] {
  const groups = new Map<string, AuditEntry[]>();
  for (const e of items) {
    if (stageOf(e) === null || !e.target) continue;
    const g = groups.get(e.target.id);
    if (g) g.push(e);
    else groups.set(e.target.id, [e]);
  }
  const out: HistoryItem[] = [];
  const placed = new Set<string>();
  for (const e of items) {
    const id = stageOf(e) !== null ? e.target?.id : undefined;
    const group = id ? groups.get(id) : undefined;
    if (!id || !group || group.length < 2) {
      out.push({ type: 'entry', entry: e });
      continue;
    }
    if (placed.has(id)) continue;
    placed.add(id);
    out.push(thread(id, group));
  }
  return out;
}

function thread(id: string, group: AuditEntry[]): AlertThread {
  const entries = [...group].sort(
    (a, b) =>
      ms(a.at) - ms(b.at) ||
      STAGES.indexOf(stageOf(a) as Stage) - STAGES.indexOf(stageOf(b) as Stage),
  );
  const first = entries[0] as AuditEntry;
  const last = entries[entries.length - 1] as AuditEntry;
  const steps = entries.map((e) => ({
    stage: stageOf(e) as Stage,
    at: e.at,
    offset_s: Math.max(0, Math.round((ms(e.at) - ms(first.at)) / 1000)),
    entry: e,
  }));
  const opened = steps.find((s) => s.stage === 'opened');
  const closed = [...steps].reverse().find((s) => s.stage === 'closed');
  const label = first.target?.label ?? '';
  return {
    type: 'thread',
    id,
    label,
    title: opened ? titleOf(opened.entry.summary_ro) : `Alertă la ${label}`,
    start: first.at,
    latest: last.at,
    steps,
    duration_s:
      opened && closed ? Math.max(0, Math.round((ms(closed.at) - ms(opened.at)) / 1000)) : null,
    entries,
  };
}

/** The day an item belongs to: an entry's own time, a thread's newest one. */
export const itemTime = (i: HistoryItem) => (i.type === 'entry' ? i.entry.at : i.latest);
