// Pure helpers behind the zone editor. All coordinates are normalised to [0,1]
// relative to the camera image, matching the Zone contract consumed by the edge.
import type { Zone } from '../contracts';

export type Point = [number, number];

export interface Draft {
  points: Point[];
  closed: boolean;
}

export interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Clicking within this normalised distance of the first point closes the polygon. */
export const CLOSE_RADIUS = 0.03;

const round4 = (n: number) => Math.round(n * 10_000) / 10_000;
const clamp01 = (n: number) => Math.min(1, Math.max(0, n));

export const emptyDraft = (): Draft => ({ points: [], closed: false });

export function normaliseClick(clientX: number, clientY: number, rect: Rect): Point {
  if (rect.width <= 0 || rect.height <= 0) return [0, 0];
  return [
    round4(clamp01((clientX - rect.left) / rect.width)),
    round4(clamp01((clientY - rect.top) / rect.height)),
  ];
}

function distance(a: Point, b: Point): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

export function addPoint(draft: Draft, p: Point): Draft {
  if (draft.closed) return draft;
  const first = draft.points[0];
  const last = draft.points[draft.points.length - 1];
  if (last && distance(last, p) < 1e-6) return draft;
  if (first && draft.points.length >= 3 && distance(first, p) <= CLOSE_RADIUS) {
    return { points: draft.points, closed: true };
  }
  return { points: [...draft.points, p], closed: false };
}

export function closeDraft(draft: Draft): Draft {
  if (draft.closed || draft.points.length < 3) return draft;
  return { points: draft.points, closed: true };
}

export function undoPoint(draft: Draft): Draft {
  return { points: draft.points.slice(0, -1), closed: false };
}

export function draftToZone(
  draft: Draft,
  meta: { id: string; name: string; tag: string },
): Zone | null {
  const name = meta.name.trim();
  if (!draft.closed || draft.points.length < 3 || name === '') return null;
  return { id: meta.id, name, tag: meta.tag, polygon: draft.points as Zone['polygon'] };
}

/** Ray casting; points exactly on an edge may fall either way, which is fine for clicks. */
export function pointInPolygon(p: Point, polygon: readonly Point[]): boolean {
  const [x, y] = p;
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i] as Point;
    const [xj, yj] = polygon[j] as Point;
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** Id of the topmost zone (drawn last) containing the point, or null. */
export function hitTest(p: Point, zones: readonly Zone[]): string | null {
  for (let i = zones.length - 1; i >= 0; i--) {
    const z = zones[i] as Zone;
    if (pointInPolygon(p, z.polygon)) return z.id;
  }
  return null;
}

export function updateZone(
  zones: readonly Zone[],
  id: string,
  patch: Partial<Omit<Zone, 'id'>>,
): Zone[] {
  return zones.map((z) => (z.id === id ? { ...z, ...patch } : z));
}

export function deleteZone(zones: readonly Zone[], id: string): Zone[] {
  return zones.filter((z) => z.id !== id);
}

/** SVG `points` attribute for a polygon in a 0..1 viewBox. */
export function toSvgPoints(points: readonly Point[]): string {
  return points.map(([x, y]) => `${x},${y}`).join(' ');
}
