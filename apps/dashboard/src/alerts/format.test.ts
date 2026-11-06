import { describe, expect, it } from 'vitest';
import { duration } from './format';

describe('duration', () => {
  it('reads as seconds under a minute and as minutes and seconds above', () => {
    expect(duration(40)).toBe('40 s');
    expect(duration(110)).toBe('1 min 50 s');
  });

  it('leaves out "0 s" on a whole minute', () => {
    expect(duration(120)).toBe('2 min');
    expect(duration(60)).toBe('1 min');
  });

  it('never puts two spaces between a number and its unit', () => {
    for (const s of [0, 9, 40, 59.6, 61, 120, 3599]) expect(duration(s)).not.toMatch(/\s\s/);
  });
});
