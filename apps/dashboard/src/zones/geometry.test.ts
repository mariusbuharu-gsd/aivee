import { describe, expect, it } from 'vitest';
import type { Zone } from '../contracts';
import {
  CLOSE_RADIUS,
  addPoint,
  closeDraft,
  deleteZone,
  draftToZone,
  emptyDraft,
  hitTest,
  normaliseClick,
  pointInPolygon,
  undoPoint,
  updateZone,
  type Draft,
} from './geometry';

const rect = { left: 100, top: 50, width: 400, height: 200 };

const square: Zone['polygon'] = [
  [0.1, 0.1],
  [0.4, 0.1],
  [0.4, 0.4],
  [0.1, 0.4],
];

function zone(id: string, polygon: Zone['polygon'] = square): Zone {
  return { id, name: id, tag: 'table', polygon };
}

function drawn(...points: [number, number][]): Draft {
  return points.reduce(addPoint, emptyDraft());
}

describe('normaliseClick', () => {
  it('maps client coordinates into [0,1] relative to the element', () => {
    expect(normaliseClick(300, 150, rect)).toEqual([0.5, 0.5]);
    expect(normaliseClick(100, 50, rect)).toEqual([0, 0]);
    expect(normaliseClick(500, 250, rect)).toEqual([1, 1]);
  });

  it('clamps clicks outside the element', () => {
    expect(normaliseClick(0, 400, rect)).toEqual([0, 1]);
    expect(normaliseClick(900, -20, rect)).toEqual([1, 0]);
  });

  it('rounds to 4 decimals so payloads stay small', () => {
    expect(normaliseClick(100 + 400 / 3, 50, rect)).toEqual([0.3333, 0]);
  });

  it('returns the origin for a zero-sized element instead of NaN', () => {
    expect(normaliseClick(10, 10, { left: 0, top: 0, width: 0, height: 0 })).toEqual([0, 0]);
  });
});

describe('addPoint', () => {
  it('appends points to an open draft', () => {
    const d = drawn([0.1, 0.1], [0.5, 0.1]);
    expect(d.points).toEqual([
      [0.1, 0.1],
      [0.5, 0.1],
    ]);
    expect(d.closed).toBe(false);
  });

  it('closes the polygon when clicking near the first point with 3+ points', () => {
    const d = drawn([0.1, 0.1], [0.5, 0.1], [0.5, 0.5], [0.1 + CLOSE_RADIUS / 2, 0.1]);
    expect(d.closed).toBe(true);
    expect(d.points).toHaveLength(3);
  });

  it('does not close near the first point with fewer than 3 points', () => {
    const d = drawn([0.1, 0.1], [0.5, 0.1], [0.1, 0.1]);
    expect(d.closed).toBe(false);
    expect(d.points).toHaveLength(3);
  });

  it('ignores clicks once the draft is closed', () => {
    const d = closeDraft(drawn([0.1, 0.1], [0.5, 0.1], [0.5, 0.5]));
    expect(addPoint(d, [0.9, 0.9])).toBe(d);
  });

  it('ignores a duplicate of the previous point (double click)', () => {
    const d = drawn([0.2, 0.2], [0.2, 0.2]);
    expect(d.points).toHaveLength(1);
  });
});

describe('closeDraft / undoPoint', () => {
  it('closes only with at least 3 points', () => {
    expect(closeDraft(drawn([0.1, 0.1], [0.2, 0.2])).closed).toBe(false);
    expect(closeDraft(drawn([0.1, 0.1], [0.2, 0.2], [0.1, 0.3])).closed).toBe(true);
  });

  it('removes the last point and reopens a closed draft', () => {
    const d = closeDraft(drawn([0.1, 0.1], [0.2, 0.2], [0.1, 0.3]));
    const u = undoPoint(d);
    expect(u.closed).toBe(false);
    expect(u.points).toHaveLength(2);
    expect(undoPoint(emptyDraft()).points).toEqual([]);
  });
});

describe('draftToZone', () => {
  it('builds a contract Zone from a closed draft', () => {
    const d = closeDraft(drawn([0.1, 0.1], [0.2, 0.2], [0.1, 0.3]));
    expect(draftToZone(d, { id: 'z1', name: ' Masa 1 ', tag: 'table' })).toEqual({
      id: 'z1',
      name: 'Masa 1',
      tag: 'table',
      polygon: [
        [0.1, 0.1],
        [0.2, 0.2],
        [0.1, 0.3],
      ],
    });
  });

  it('returns null for an open draft or a blank name', () => {
    expect(draftToZone(drawn([0.1, 0.1]), { id: 'z', name: 'x', tag: 'table' })).toBeNull();
    const closed = closeDraft(drawn([0.1, 0.1], [0.2, 0.2], [0.1, 0.3]));
    expect(draftToZone(closed, { id: 'z', name: '  ', tag: 'table' })).toBeNull();
  });
});

describe('pointInPolygon / hitTest', () => {
  it('detects points inside and outside a polygon', () => {
    expect(pointInPolygon([0.2, 0.2], square)).toBe(true);
    expect(pointInPolygon([0.5, 0.2], square)).toBe(false);
    expect(pointInPolygon([0.05, 0.05], square)).toBe(false);
  });

  it('handles concave polygons', () => {
    const l: Zone['polygon'] = [
      [0, 0],
      [1, 0],
      [1, 0.2],
      [0.2, 0.2],
      [0.2, 1],
      [0, 1],
    ];
    expect(pointInPolygon([0.1, 0.9], l)).toBe(true);
    expect(pointInPolygon([0.6, 0.6], l)).toBe(false);
  });

  it('returns the topmost (last drawn) zone under the point', () => {
    const zones = [zone('below'), zone('above')];
    expect(hitTest([0.2, 0.2], zones)).toBe('above');
    expect(hitTest([0.9, 0.9], zones)).toBeNull();
  });
});

describe('updateZone / deleteZone', () => {
  it('patches name and tag without touching other zones', () => {
    const zones = [zone('a'), zone('b')];
    const next = updateZone(zones, 'b', { name: 'Intrare', tag: 'entrance' });
    expect(next[1]).toMatchObject({ id: 'b', name: 'Intrare', tag: 'entrance' });
    expect(next[0]).toBe(zones[0]);
  });

  it('removes a zone by id', () => {
    expect(deleteZone([zone('a'), zone('b')], 'a').map((z) => z.id)).toEqual(['b']);
    expect(deleteZone([zone('a')], 'missing')).toHaveLength(1);
  });
});
