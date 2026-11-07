import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { OfflineBanner } from './OfflineBanner';
import { probe } from './reachability';

describe('probe', () => {
  it('is true when /healthz answers ok', async () => {
    const f = vi.fn<typeof fetch>(async () => new Response('{}', { status: 200 }));
    expect(await probe('http://api:8000/', f)).toBe(true);
    expect(f.mock.calls[0]?.[0]).toBe('http://api:8000/healthz');
  });

  it('is false on a network error or a 5xx', async () => {
    expect(
      await probe('http://api', vi.fn<typeof fetch>().mockRejectedValue(new TypeError())),
    ).toBe(false);
    expect(
      await probe(
        'http://api',
        vi.fn<typeof fetch>(async () => new Response('', { status: 502 })),
      ),
    ).toBe(false);
  });

  it('has nothing to reach in mock mode', async () => {
    const f = vi.fn<typeof fetch>();
    expect(await probe('', f)).toBe(true);
    expect(f).not.toHaveBeenCalled();
  });
});

describe('OfflineBanner', () => {
  it('says Offline when the API is unreachable', () => {
    render(<OfflineBanner reachable={false} />);
    expect(screen.getByRole('status')).toHaveTextContent('Offline');
  });

  it('renders nothing while reachable', () => {
    const { container } = render(<OfflineBanner reachable />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('manifest colours', () => {
  it('come from the design tokens', async () => {
    const { token } = await import('./plugin');
    const css = readFileSync(`${process.cwd()}/src/styles.css`, 'utf8');
    expect(token('ink', css)).toBe('#14161B');
    expect(token('ground', css)).toBe('#F6F7F9');
  });
});
