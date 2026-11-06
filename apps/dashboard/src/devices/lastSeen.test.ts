import { describe, expect, it } from 'vitest';
import { lastSeenRo, sinceRo } from './lastSeen';

const NOW = Date.parse('2026-11-06T20:00:00Z');
const ago = (s: number) => new Date(NOW - s * 1000).toISOString();

describe('sinceRo', () => {
  it('counts seconds, then minutes, hours and days', () => {
    expect(sinceRo(3_000)).toBe('3 s');
    expect(sinceRo(59_900)).toBe('59 s');
    expect(sinceRo(60_000)).toBe('1 min');
    expect(sinceRo(14 * 60_000 + 30_000)).toBe('14 min');
    expect(sinceRo(3 * 3_600_000)).toBe('3 h');
    expect(sinceRo(26 * 3_600_000)).toBe('1 zi');
    expect(sinceRo(3 * 86_400_000)).toBe('3 zile');
  });

  it('never goes negative when the browser clock runs behind the server', () => {
    expect(sinceRo(-4_000)).toBe('0 s');
  });
});

describe('lastSeenRo', () => {
  it('says when an online camera last sent a frame', () => {
    expect(lastSeenRo(true, ago(3), NOW)).toBe('ultima imagine acum 3 s');
  });

  it('says how long an offline camera has been gone', () => {
    expect(lastSeenRo(false, ago(14 * 60), NOW)).toBe('offline de 14 min');
  });

  it('says nothing without a time or with a bad one', () => {
    expect(lastSeenRo(true, null, NOW)).toBeNull();
    expect(lastSeenRo(false, undefined, NOW)).toBeNull();
    expect(lastSeenRo(true, 'not a date', NOW)).toBeNull();
  });
});
