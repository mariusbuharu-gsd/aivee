import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BusyLabel, Loading } from './Eyes';

describe('Eyes loader', () => {
  it('announces what is loading and hides the eyes from screen readers', () => {
    const { container } = render(<Loading>Se încarcă sala…</Loading>);
    expect(screen.getByRole('status')).toHaveTextContent('Se încarcă sala…');
    expect(container.querySelector('svg.eyes-look')).toHaveAttribute('aria-hidden', 'true');
  });

  it('shows the eyes in a button only while busy, keeping the busy text as its name', () => {
    const { rerender, container } = render(
      <button type="button">
        <BusyLabel busy={false} idle="Salvează">
          Se salvează…
        </BusyLabel>
      </button>,
    );
    expect(screen.getByRole('button', { name: 'Salvează' })).toBeInTheDocument();
    expect(container.querySelector('svg')).toBeNull();
    rerender(
      <button type="button">
        <BusyLabel busy idle="Salvează">
          Se salvează…
        </BusyLabel>
      </button>,
    );
    expect(screen.getByRole('button', { name: 'Se salvează…' })).toBeInTheDocument();
    expect(container.querySelector('svg.eyes-look')).not.toBeNull();
  });
});
