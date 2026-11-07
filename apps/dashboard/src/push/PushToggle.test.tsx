import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { PushToggle } from './PushToggle';
import type { PushService, PushState } from './service';

function fakeService(initial: PushState, overrides: Partial<PushService> = {}): PushService {
  return {
    supported: initial !== 'unsupported',
    state: vi.fn(async () => initial),
    enable: vi.fn(async () => 'on' as const),
    disable: vi.fn(async () => 'off' as const),
    sendTest: vi.fn(async () => ({ sent: 1, removed: 0, failed: 0 })),
    ...overrides,
  } as unknown as PushService;
}

describe('PushToggle', () => {
  it('explains an unsupported browser and offers no button', async () => {
    render(<PushToggle service={fakeService('unsupported')} />);
    expect(await screen.findByText(/nu primește notificări/)).toBeInTheDocument();
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  });

  it('tells how to unblock when denied', async () => {
    render(<PushToggle service={fakeService('denied')} />);
    expect(await screen.findByText('blocate')).toBeInTheDocument();
    expect(screen.getByText(/setările site-ului/)).toBeInTheDocument();
  });

  it('turns notifications on, then sends a test', async () => {
    const service = fakeService('off');
    render(<PushToggle service={service} />);
    const toggle = await screen.findByRole('switch', { name: 'Activează notificările' });
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    await userEvent.click(toggle);
    expect(service.enable).toHaveBeenCalled();
    expect(await screen.findByRole('switch', { name: 'Oprește notificările' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    expect(screen.getByText('active')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Trimite un test' }));
    expect(await screen.findByText('Am trimis un test pe 1 dispozitiv.')).toBeInTheDocument();
  });

  it('shows the error message when enabling fails', async () => {
    const service = fakeService('off', {
      enable: vi.fn(async () => {
        throw new Error('Serverul nu răspunde. Verifică conexiunea.');
      }),
    });
    render(<PushToggle service={service} />);
    await userEvent.click(await screen.findByRole('switch'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Serverul nu răspunde');
  });
});

describe('PushToggle placements', () => {
  const page = (state: PushState) => {
    const service = fakeService(state);
    return render(
      <MemoryRouter>
        <PushToggle service={service} variant="banner" />
        <PushToggle service={service} variant="actionable" />
        <PushToggle service={service} variant="note" />
      </MemoryRouter>,
    );
  };

  it('turns "indisponibil" into a banner that says what to do, and hides the card', async () => {
    const { container } = page('unavailable');
    expect(await screen.findByText('Notificări pe telefon: indisponibile')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Mergi la Locații' })).toHaveAttribute(
      'href',
      '/locatii',
    );
    expect(screen.queryByRole('heading', { name: 'Notificări pe telefon' })).toBeNull();
    // The note (non-owners) shows too here; on the page only one of banner/note is mounted.
    expect(container.querySelectorAll('#notificari')).toHaveLength(2);
  });

  it('keeps the card, alone and with the #notificari anchor, when there is a switch', async () => {
    const { container } = page('off');
    expect(await screen.findByRole('switch', { name: 'Activează notificările' })).toBeVisible();
    expect(screen.queryByText(/indisponibile/)).toBeNull();
    expect(screen.queryByText(/nu merg aici/)).toBeNull();
    expect(container.querySelectorAll('#notificari')).toHaveLength(1);
  });
});
