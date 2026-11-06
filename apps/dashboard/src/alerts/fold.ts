import type { AlertView } from '../api/client';

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
  /** Face-blurred JPEG of the moment the alert opened, when the edge sent one. */
  snapshot_url: string | null;
  /** Set when the system, not a person arriving, closed it (camera offline, deleted…). */
  closed_reason?: AlertView['closed_reason'];
  /** The vision model's second opinion, when the API sent one. */
  verification?: AlertView['verification'];
  /** `object_gone` only: the frame before the object disappeared (`snapshot_url` is after). */
  before_snapshot_url?: string | null;
}

const situation = (e: AlertView) => `${e.camera_id}|${e.rule_id}|${e.zone_id}`;

/**
 * Pair opened/closed events per (camera, rule, zone) into alerts, newest first.
 * Duplicate event ids are ignored, so replaying the socket after a reconnect is safe; a repeated
 * `opened` event only refreshes the AI verification (pending → confirmed arrives that way).
 */
export function foldAlerts(events: readonly AlertView[]): AlertItem[] {
  const byId = new Map<string, AlertItem | null>();
  const open = new Map<string, AlertItem>();
  const items: AlertItem[] = [];
  const sorted = [...events].sort((a, b) => a.at.localeCompare(b.at));
  for (const e of sorted) {
    if (byId.has(e.event_id)) {
      const known = byId.get(e.event_id);
      if (known && e.state === 'opened') withVerification(known, e);
      continue;
    }
    byId.set(e.event_id, null);
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
        snapshot_url: e.snapshot_url ?? null,
      };
      withVerification(item, e);
      byId.set(e.event_id, item);
      open.set(key, item);
      items.push(item);
    } else if (e.state === 'closed') {
      const item = open.get(key);
      if (item) {
        item.closed_at = e.at;
        if (e.closed_by === 'system') item.closed_reason = e.closed_reason ?? null;
        open.delete(key);
      }
    }
  }
  return items.reverse();
}

function withVerification(item: AlertItem, e: AlertView) {
  if (e.verification) item.verification = e.verification;
  if (e.before_snapshot_url) item.before_snapshot_url = e.before_snapshot_url;
}
