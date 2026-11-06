import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
