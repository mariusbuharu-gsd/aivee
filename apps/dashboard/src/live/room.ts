import type { AlertItem } from '../alerts/fold';
import type { CameraView } from '../api/client';

/** Seconds after which an open alert's ring is full: a visual scale, not a rule threshold. */
export const RING_FULL_S = 300;

/** Open alerts, oldest first: the one waiting longest leads. */
export function openAlerts(alerts: readonly AlertItem[]): AlertItem[] {
  return alerts
    .filter((a) => a.closed_at === null)
    .sort((a, b) => a.opened_at.localeCompare(b.opened_at));
}

/** Seconds since the alert opened, never negative. */
export function elapsed(a: Pick<AlertItem, 'opened_at'>, now: number): number {
  return Math.max(0, (now - Date.parse(a.opened_at)) / 1000);
}

/** "2:05": a ticking timer, minutes and seconds. */
export function tick(s: number): string {
  const v = Math.floor(Math.max(0, s));
  return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, '0')}`;
}

/** 0..1, how full the ring is. */
export function ringFill(s: number): number {
  return Math.min(1, Math.max(0, s / RING_FULL_S));
}

/**
 * The page's one-line state: "Totul e în regulă." when nothing waits, otherwise how many tables
 * wait. The small facts follow it (alerts today, cameras offline), only when they say something.
 */
export function roomStatus(
  open: number,
  cameras: readonly Pick<CameraView, 'online'>[],
  alertsToday: number | null,
): { title: string; facts: string[] } {
  const title =
    open === 0 ? 'Totul e în regulă.' : open === 1 ? 'O masă așteaptă.' : `${open} mese așteaptă.`;
  const facts: string[] = [];
  if (alertsToday !== null) {
    facts.push(alertsToday === 1 ? '1 alertă azi' : `${alertsToday} alerte azi`);
  }
  const off = cameras.filter((c) => !c.online).length;
  if (off > 0) facts.push(off === 1 ? '1 cameră offline' : `${off} camere offline`);
  return { title, facts };
}
