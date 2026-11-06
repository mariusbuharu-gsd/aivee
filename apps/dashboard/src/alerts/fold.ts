import type { AlertEvent } from '../contracts';

/** An alert as the user sees it: an `opened` event, plus the `closed` event that ended it. */
export interface AlertItem {
  key: string;
  rule_id: string;
  camera_id: string;
  zone_id: string;
  summary_ro: string;
  opened_at: string;
  closed_at: string | null;
  snapshot: boolean;
}

const situation = (e: AlertEvent) => `${e.camera_id}|${e.rule_id}|${e.zone_id}`;

/**
 * Pair opened/closed events per (camera, rule, zone) into alerts, newest first.
 * Duplicate event ids are ignored, so replaying the socket after a reconnect is safe.
 */
export function foldAlerts(events: readonly AlertEvent[]): AlertItem[] {
  const seen = new Set<string>();
  const open = new Map<string, AlertItem>();
  const items: AlertItem[] = [];
  const sorted = [...events].sort((a, b) => a.at.localeCompare(b.at));
  for (const e of sorted) {
    if (seen.has(e.event_id)) continue;
    seen.add(e.event_id);
    const key = situation(e);
    if (e.state === 'opened') {
      if (open.has(key)) continue;
      const item: AlertItem = {
        key: e.event_id,
        rule_id: e.rule_id,
        camera_id: e.camera_id,
        zone_id: e.zone_id,
        summary_ro: e.summary_ro,
        opened_at: e.at,
        closed_at: null,
        snapshot: e.snapshot ?? false,
      };
      open.set(key, item);
      items.push(item);
    } else {
      const item = open.get(key);
      if (item) {
        item.closed_at = e.at;
        open.delete(key);
      }
    }
  }
  return items.reverse();
}
