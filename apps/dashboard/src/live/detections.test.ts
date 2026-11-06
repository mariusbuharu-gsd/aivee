import { describe, expect, it } from 'vitest';
import type { Detections } from '../contracts';
import { detectionLabel, fromContract, parseDetections } from './detections';

describe('parseDetections', () => {
  it('reads the API frame as is', () => {
    const data = [
      {
        track_id: 7,
        role: 'staff',
        box: [0.1, 0.2, 0.3, 0.4],
        staff_score: 0.9,
        raised_hand: false,
      },
      {
        track_id: 12,
        role: 'guest',
        box: [0.5, 0.5, 0.1, 0.2],
        staff_score: 0.1,
        raised_hand: true,
      },
    ];
    expect(parseDetections(data)).toEqual([
      {
        track_id: 7,
        role: 'staff',
        box: [0.1, 0.2, 0.3, 0.4],
        staff_score: 0.9,
        raised_hand: false,
      },
      {
        track_id: 12,
        role: 'guest',
        box: [0.5, 0.5, 0.1, 0.2],
        staff_score: 0.1,
        raised_hand: true,
      },
    ]);
  });

  it('drops malformed items and clamps boxes to the frame', () => {
    const out = parseDetections([
      null,
      { track_id: '1', role: 'guest', box: [0, 0, 1, 1] },
      { track_id: 2, role: 'robot', box: [0, 0, 1, 1] },
      { track_id: 3, role: 'guest', box: [0, 0, 1] },
      { track_id: 4, role: 'guest', box: [0.5, -0.1, 0.8, 0.3] },
    ]);
    expect(out).toEqual([
      {
        track_id: 4,
        role: 'guest',
        box: [0.5, 0, 0.5, 0.3],
        staff_score: undefined,
        raised_hand: false,
      },
    ]);
  });

  it('returns null when data is not a list', () => {
    expect(parseDetections({ nope: true })).toBeNull();
  });
});

describe('fromContract', () => {
  it('turns x1,y1,x2,y2 into x,y,w,h', () => {
    const d: Detections = {
      camera_id: 'cam-01',
      ts: '2026-11-06T12:00:00Z',
      tracks: [{ track_id: 1, role: 'guest', staff_score: 0.2, bbox: [0.1, 0.2, 0.4, 0.6] }],
    };
    const [t] = fromContract(d);
    expect(t?.box[0]).toBeCloseTo(0.1);
    expect(t?.box[2]).toBeCloseTo(0.3);
    expect(t?.box[3]).toBeCloseTo(0.4);
    expect(t?.raised_hand).toBe(false);
  });
});

describe('detectionLabel', () => {
  it('names people by role in Romanian and flags a raised hand', () => {
    expect(detectionLabel({ track_id: 7, role: 'staff', box: [0, 0, 1, 1] })).toBe('angajat #7');
    expect(
      detectionLabel({ track_id: 12, role: 'guest', box: [0, 0, 1, 1], raised_hand: true }),
    ).toBe('mână ridicată #12');
  });
});
