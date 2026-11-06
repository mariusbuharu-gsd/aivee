// Live detection boxes: parsing the API's `/ws/events` frames and the edge contract.
// Pure functions, no DOM, so the overlay logic is tested without a browser.
import type { Detection } from '../api/client';
import type { Detections } from '../contracts';

const ROLES = new Set<Detection['role']>(['guest', 'staff']);

/** Romanian labels; staff are named by role, never by person. */
export const ROLE_LABEL: Record<Detection['role'], string> = { staff: 'angajat', guest: 'client' };
export const RAISED_HAND_LABEL = 'mână ridicată';

const clamp01 = (n: number) => Math.min(1, Math.max(0, n));
const isNum = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);

/**
 * Validate the `data` of a `{type: 'detections'}` frame. Malformed items are dropped, boxes are
 * clamped to the frame. Returns null when `data` is not a list at all.
 */
export function parseDetections(data: unknown): Detection[] | null {
  if (!Array.isArray(data)) return null;
  const out: Detection[] = [];
  for (const item of data as unknown[]) {
    if (!item || typeof item !== 'object') continue;
    const d = item as Record<string, unknown>;
    const box = d.box;
    if (!isNum(d.track_id) || !ROLES.has(d.role as Detection['role'])) continue;
    if (!Array.isArray(box) || box.length !== 4 || !box.every(isNum)) continue;
    const [x, y, w, h] = (box as number[]).map(clamp01) as [number, number, number, number];
    out.push({
      track_id: d.track_id,
      role: d.role as Detection['role'],
      box: [x, y, Math.min(w, 1 - x), Math.min(h, 1 - y)],
      staff_score: isNum(d.staff_score) ? d.staff_score : undefined,
      raised_hand: d.raised_hand === true,
    });
  }
  return out;
}

/** Edge contract (`x1, y1, x2, y2`) to the overlay's `[x, y, width, height]`. */
export function fromContract(d: Detections): Detection[] {
  return (d.tracks ?? []).map((t) => {
    const [x1, y1, x2, y2] = t.bbox;
    return {
      track_id: t.track_id,
      role: t.role,
      box: [x1, y1, x2 - x1, y2 - y1],
      staff_score: t.staff_score,
      raised_hand: t.raised_hand ?? false,
    };
  });
}

/** Short enough to fit a phone tile: a guest's raised hand replaces the role word. */
export function detectionLabel(d: Detection): string {
  if (d.raised_hand && d.role === 'guest') return `${RAISED_HAND_LABEL} #${d.track_id}`;
  const role = `${ROLE_LABEL[d.role]} #${d.track_id}`;
  return d.raised_hand ? `${role} · ${RAISED_HAND_LABEL}` : role;
}
