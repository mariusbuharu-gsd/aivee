import { describe, expect, it } from 'vitest';
import { ApiError } from '../api/client';
import { toLoadError } from './context';

describe('toLoadError', () => {
  it('tells a dead network from a missing permission', () => {
    expect(toLoadError(new ApiError('Serverul nu răspunde.', 'network')).kind).toBe('network');
    expect(toLoadError(new ApiError('Nu ai voie.', 'forbidden', 403)).kind).toBe('forbidden');
    expect(toLoadError(new ApiError('Ups', 'error', 500))).toEqual({
      kind: 'other',
      message: 'Ups',
    });
    expect(toLoadError('text').message).toBe('text');
  });
});
